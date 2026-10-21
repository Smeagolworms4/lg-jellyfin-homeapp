/*
 * homepatch — LD_PRELOAD pour com.webos.app.home (accueil Flutter webOS).
 *
 * L'accueil est du Dart compilé : on ne touche pas à l'app. On s'intercale
 * entre elle et le bus luna. Chaque réponse JSON reçue peut être remplacée,
 * fusionnée (RFC 7386) ou retouchée champ par champ selon un fichier de règles,
 * relu à chaud dès qu'il change. Sans règle applicable, tout passe tel quel.
 *
 * Règles : $HOMEPATCH_DIR/rules.json (défaut /media/developer/jellyhome)
 *   {
 *     "log": true,                         // journal de tous les appels luna
 *     "rules": [
 *       { "uri": "luna://com.webos.service.admanager/requestBannerInfo*",
 *         "request": "sous-chaîne optionnelle de la requête",
 *         "replace": { ... }               // réponse entière
 *         "file":    "banner.json",        // réponse entière depuis un fichier
 *         "merge":   { ... },              // merge-patch RFC 7386
 *         "set":     { "/a/0/b": "valeur" },// chemin → valeur
 *         "remove":  [ "/a/[id=x]" ],      // chemins à supprimer
 *         "json":    [ "/serverResponse/response" ], // chaînes JSON à décoder
 *         "save":    "orig.json",          // copie la réponse d'origine
 *         "onCall":  "last.json",          // copie l'appel sortant (réponse intacte)
 *         "drop":    true }                // la réponse n'arrive jamais
 *     ]
 *   }
 * "uri" accepte un '*' final (préfixe). Dans un chemin, un segment "[clé=val]"
 * désigne le premier élément d'un tableau dont le champ clé vaut val. Les
 * règles s'appliquent dans l'ordre ; dans une règle : save, json (décodage), replace
 * ou file, merge, set, remove, puis json (ré-encodage).
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <pthread.h>
#include <unistd.h>

#include "vendor/cJSON.h"
#include "vendor/cJSON_Utils.h"

typedef struct LSHandle LSHandle;
typedef struct LSMessage LSMessage;
typedef unsigned long LSMessageToken;
typedef struct LSError LSError;
typedef bool (*LSFilterFunc)(LSHandle *sh, LSMessage *reply, void *ctx);

typedef bool (*call_fn)(LSHandle *, const char *, const char *, LSFilterFunc,
                        void *, LSMessageToken *, LSError *);
typedef bool (*call_app_fn)(LSHandle *, const char *, const char *, const char *,
                            LSFilterFunc, void *, LSMessageToken *, LSError *);
typedef const char *(*payload_fn)(LSMessage *);

static char g_dir[256];
static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;

/* ------------------------------------------------------------------ règles */

static cJSON *g_rules;          /* tableau "rules" */
static bool g_log;
static time_t g_mtime;
static off_t g_size;
static time_t g_checked;

static char *read_file(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = n >= 0 ? malloc(n + 1) : NULL;
    if (buf && fread(buf, 1, n, f) == (size_t)n)
        buf[n] = 0;
    else {
        free(buf);
        buf = NULL;
    }
    fclose(f);
    return buf;
}

static void logf_(const char *fmt, ...)
{
    char path[300];
    snprintf(path, sizeof path, "%s/luna.log", g_dir);
    FILE *f = fopen(path, "a");
    if (!f)
        return;
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    struct tm tm;
    localtime_r(&ts.tv_sec, &tm);
    fprintf(f, "%02d:%02d:%02d.%03ld ", tm.tm_hour, tm.tm_min, tm.tm_sec,
            ts.tv_nsec / 1000000);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}

/* Relit rules.json s'il a changé — au plus une fois par seconde. */
static void reload_rules(void)
{
    time_t now = time(NULL);
    if (now == g_checked)
        return;
    g_checked = now;

    char path[300];
    snprintf(path, sizeof path, "%s/rules.json", g_dir);
    struct stat st;
    if (stat(path, &st) != 0) {
        if (g_rules) {
            cJSON_Delete(g_rules);
            g_rules = NULL;
            g_log = false;
        }
        g_mtime = 0;
        return;
    }
    if (st.st_mtime == g_mtime && st.st_size == g_size)
        return;
    g_mtime = st.st_mtime;
    g_size = st.st_size;

    char *txt = read_file(path);
    cJSON *root = txt ? cJSON_Parse(txt) : NULL;
    free(txt);
    if (!root) {
        /* JSON invalide : on garde les règles précédentes */
        logf_("ERREUR rules.json illisible, règles précédentes conservées");
        return;
    }
    cJSON_Delete(g_rules);
    g_log = cJSON_IsTrue(cJSON_GetObjectItem(root, "log"));
    g_rules = cJSON_DetachItemFromObject(root, "rules");
    cJSON_Delete(root);
    logf_("règles rechargées (%d)", g_rules ? cJSON_GetArraySize(g_rules) : 0);
}

static bool uri_match(const char *pattern, const char *uri)
{
    size_t n = strlen(pattern);
    if (n && pattern[n - 1] == '*')
        return strncmp(pattern, uri, n - 1) == 0;
    return strcmp(pattern, uri) == 0;
}

/* Segment de chemin dans un tableau : index, "-" (fin ; "-1", "-2"… aussi, pour
 * ajouter plusieurs éléments malgré l'unicité des clés JSON), ou "[clé=valeur]"
 * (premier élément dont le champ clé vaut valeur, en texte). -1 si absent. */
static int array_index(cJSON *arr, const char *tok)
{
    if (tok[0] == '-')
        return cJSON_GetArraySize(arr);
    if (tok[0] != '[')
        return atoi(tok);
    char key[128];
    const char *eq = strchr(tok, '='), *end = strrchr(tok, ']');
    if (!eq || !end || eq > end || (size_t)(eq - tok - 1) >= sizeof key)
        return -1;
    snprintf(key, sizeof key, "%.*s", (int)(eq - tok - 1), tok + 1);
    int i = 0;
    cJSON *el;
    cJSON_ArrayForEach(el, arr) {
        cJSON *f = cJSON_GetObjectItemCaseSensitive(el, key);
        char buf[64];
        const char *v = cJSON_GetStringValue(f);
        if (!v && cJSON_IsNumber(f)) {
            snprintf(buf, sizeof buf, "%g", f->valuedouble);
            v = buf;
        }
        if (v && strlen(v) == (size_t)(end - eq - 1) && !strncmp(v, eq + 1, end - eq - 1))
            return i;
        i++;
    }
    return -1;
}

/* Parcourt path ("/a/0/[id=x]/b"). Si value : y pose une copie, en créant les
 * objets intermédiaires ; sinon supprime le nœud. Renvoie le nœud final. */
static cJSON *walk(cJSON *root, const char *path, cJSON *value, bool remove)
{
    char *dup = strdup(path), *save = NULL;
    cJSON *node = root;
    char *tok = strtok_r(dup, "/", &save);
    if (!tok && value) {
        free(dup);
        return NULL; /* la racine se remplace avec "replace" */
    }
    while (tok && node) {
        char *next = strtok_r(NULL, "/", &save);
        bool last = !next && (value || remove);
        if (cJSON_IsArray(node)) {
            int idx = array_index(node, tok);
            if (idx < 0) {
                node = NULL;
                break;
            }
            if (last && remove) {
                cJSON_DeleteItemFromArray(node, idx);
                node = NULL;
                break;
            }
            if (last) {
                if (idx < cJSON_GetArraySize(node))
                    cJSON_ReplaceItemInArray(node, idx, cJSON_Duplicate(value, 1));
                else
                    cJSON_AddItemToArray(node, cJSON_Duplicate(value, 1));
            }
            node = cJSON_GetArrayItem(node, idx < cJSON_GetArraySize(node) ? idx
                                                   : cJSON_GetArraySize(node) - 1);
        } else if (cJSON_IsObject(node)) {
            if (last && remove) {
                cJSON_DeleteItemFromObjectCaseSensitive(node, tok);
                node = NULL;
                break;
            }
            if (last) {
                cJSON_DeleteItemFromObjectCaseSensitive(node, tok);
                cJSON_AddItemToObject(node, tok, cJSON_Duplicate(value, 1));
            } else if (value && !cJSON_GetObjectItemCaseSensitive(node, tok)) {
                cJSON_AddItemToObject(node, tok, cJSON_CreateObject());
            }
            node = cJSON_GetObjectItemCaseSensitive(node, tok);
        } else {
            node = NULL;
        }
        tok = next;
    }
    free(dup);
    return node;
}

/* Les réponses SDP embarquent du JSON sérialisé dans une chaîne
 * ("serverResponse.response") : on le décode le temps d'appliquer la règle. */
static void decode_paths(cJSON *doc, cJSON *paths, bool encode)
{
    cJSON *p;
    cJSON_ArrayForEach(p, paths) {
        const char *path = cJSON_GetStringValue(p);
        cJSON *node = path ? walk(doc, path, NULL, false) : NULL;
        if (!node)
            continue;
        cJSON *repl = NULL;
        if (!encode && cJSON_IsString(node)) {
            repl = cJSON_Parse(node->valuestring);
        } else if (encode && !cJSON_IsString(node)) {
            char *txt = cJSON_PrintUnformatted(node);
            repl = cJSON_CreateString(txt);
            free(txt);
        }
        if (repl) {
            walk(doc, path, repl, false);
            cJSON_Delete(repl);
        }
    }
}

/* Renvoie la réponse réécrite (à libérer), NULL si inchangée, "" si à jeter. */
static char *apply_rules(const char *uri, const char *req, const char *resp)
{
    if (!g_rules)
        return NULL;
    cJSON *doc = NULL;
    bool changed = false, drop = false;
    cJSON *rule;
    cJSON_ArrayForEach(rule, g_rules) {
        const char *ruri = cJSON_GetStringValue(cJSON_GetObjectItem(rule, "uri"));
        if (!ruri || !uri_match(ruri, uri))
            continue;
        const char *rreq = cJSON_GetStringValue(cJSON_GetObjectItem(rule, "request"));
        if (rreq && (!req || !strstr(req, rreq)))
            continue;
        if (cJSON_IsFalse(cJSON_GetObjectItem(rule, "enabled")))
            continue;

        /* Sauvegarde de la réponse d'origine, pour la resservir ailleurs. */
        const char *save = cJSON_GetStringValue(cJSON_GetObjectItem(rule, "save"));
        if (save) {
            char path[512], tmp[520];
            snprintf(path, sizeof path, save[0] == '/' ? "%s%s" : "%s/%s",
                     save[0] == '/' ? "" : g_dir, save);
            snprintf(tmp, sizeof tmp, "%s.tmp", path);
            FILE *f = fopen(tmp, "w");
            if (f) {
                fputs(resp, f);
                fclose(f);
                rename(tmp, path);
            }
        }

        if (!doc)
            doc = cJSON_Parse(resp);
        if (!doc)
            doc = cJSON_CreateObject();

        if (cJSON_IsTrue(cJSON_GetObjectItem(rule, "drop")))
            drop = true;

        cJSON *jpaths = cJSON_GetObjectItem(rule, "json");
        decode_paths(doc, jpaths, false);

        cJSON *rep = cJSON_GetObjectItem(rule, "replace");
        const char *file = cJSON_GetStringValue(cJSON_GetObjectItem(rule, "file"));
        if (file) {
            char path[512];
            if (file[0] == '/')
                snprintf(path, sizeof path, "%s", file);
            else
                snprintf(path, sizeof path, "%s/%s", g_dir, file);
            char *txt = read_file(path);
            cJSON *fdoc = txt ? cJSON_Parse(txt) : NULL;
            free(txt);
            if (fdoc) {
                cJSON_Delete(doc);
                doc = fdoc;
                changed = true;
            } else {
                logf_("ERREUR fichier %s absent ou invalide", path);
            }
        } else if (rep) {
            cJSON_Delete(doc);
            doc = cJSON_Duplicate(rep, 1);
            changed = true;
        }

        cJSON *merge = cJSON_GetObjectItem(rule, "merge");
        if (merge) {
            doc = cJSONUtils_MergePatchCaseSensitive(doc, merge);
            changed = true;
        }

        cJSON *set = cJSON_GetObjectItem(rule, "set");
        cJSON *kv;
        cJSON_ArrayForEach(kv, set) {
            walk(doc, kv->string, kv, false);
            changed = true;
        }

        cJSON *rm = cJSON_GetObjectItem(rule, "remove");
        cJSON_ArrayForEach(kv, rm) {
            if (cJSON_IsString(kv))
                walk(doc, kv->valuestring, NULL, true);
            changed = true;
        }

        decode_paths(doc, jpaths, true);
    }
    char *out = NULL;
    if (drop)
        out = strdup("");
    else if (changed && doc)
        out = cJSON_PrintUnformatted(doc);
    cJSON_Delete(doc);
    return out;
}

/* ------------------------------------------------------------- interception */

typedef struct {
    LSFilterFunc cb;
    void *ctx;
    char *uri;
    char *req;
    bool once;
} Wrap;

/* Message en cours de traitement par un callback enveloppé, et sa réécriture. */
static __thread LSMessage *t_msg;
static __thread Wrap *t_wrap;
static __thread char *t_out;
static __thread bool t_done;
static __thread int t_depth;  /* LSCall* peut s'appeler en interne */

static payload_fn real_payload;

/* libluna-service2 est chargée par dlopen (portée locale) depuis l'embedder :
 * RTLD_NEXT ne la voit pas, on la vise directement. */
static void *real_sym(const char *name)
{
    static void *lib;
    if (!lib)
        lib = dlopen("libluna-service2.so.3", RTLD_LAZY);
    void *f = lib ? dlsym(lib, name) : NULL;
    if (!f)
        f = dlsym(RTLD_NEXT, name);
    if (!f)
        logf_("ERREUR symbole introuvable : %s", name);
    return f;
}

static bool wrapped_cb(LSHandle *sh, LSMessage *msg, void *ctx)
{
    Wrap *w = ctx;
    LSMessage *pm = t_msg;
    Wrap *pw = t_wrap;
    char *po = t_out;
    bool pd = t_done;
    t_msg = msg;
    t_wrap = w;
    t_out = NULL;
    t_done = false;

    /* Évaluation immédiate : permet aussi de jeter la réponse. */
    if (!real_payload)
        real_payload = (payload_fn)real_sym("LSMessageGetPayload");
    const char *payload = real_payload ? real_payload(msg) : NULL;
    bool forward = true;
    if (payload) {
        pthread_mutex_lock(&g_lock);
        reload_rules();
        t_out = apply_rules(w->uri, w->req, payload);
        if (g_log)
            logf_("RESP %s %s%s", w->uri, payload, t_out ? "  [PATCHÉ]" : "");
        pthread_mutex_unlock(&g_lock);
        t_done = true;
        if (t_out && !*t_out)
            forward = false;
    }

    bool ret = forward ? w->cb(sh, msg, w->ctx) : true;

    free(t_out);
    t_msg = pm;
    t_wrap = pw;
    t_out = po;
    t_done = pd;
    if (w->once) {
        free(w->uri);
        free(w->req);
        free(w);
    }
    return ret;
}

const char *LSMessageGetPayload(LSMessage *msg)
{
    if (!real_payload)
        real_payload = (payload_fn)real_sym("LSMessageGetPayload");
    if (!real_payload)
        return NULL;
    if (msg && msg == t_msg && t_done && t_out && *t_out)
        return t_out;
    return real_payload(msg);
}

/* Règle "onCall" : copie (horodatée) d'un appel sortant de l'accueil vers un
 * fichier, pour qu'un service puisse y réagir. L'appel lui-même part inchangé. */
static void observe_call(const char *uri, const char *payload)
{
    pthread_mutex_lock(&g_lock);
    reload_rules();
    cJSON *rule;
    cJSON_ArrayForEach(rule, g_rules) {
        const char *file = cJSON_GetStringValue(cJSON_GetObjectItem(rule, "onCall"));
        const char *ruri = cJSON_GetStringValue(cJSON_GetObjectItem(rule, "uri"));
        const char *rreq = cJSON_GetStringValue(cJSON_GetObjectItem(rule, "request"));
        if (!file || !ruri || !uri_match(ruri, uri) || (rreq && !strstr(payload, rreq)))
            continue;
        char path[512], tmp[520];
        snprintf(path, sizeof path, file[0] == '/' ? "%s%s" : "%s/%s",
                 file[0] == '/' ? "" : g_dir, file);
        snprintf(tmp, sizeof tmp, "%s.tmp", path);
        FILE *f = fopen(tmp, "w");
        if (f) {
            fprintf(f, "{\"time\":%ld,\"uri\":", (long)time(NULL));
            cJSON *u = cJSON_CreateString(uri);
            char *us = cJSON_PrintUnformatted(u);
            fputs(us, f);
            free(us);
            cJSON_Delete(u);
            cJSON *pl = cJSON_Parse(payload);
            char *ps = pl ? cJSON_PrintUnformatted(pl) : NULL;
            fprintf(f, ",\"payload\":%s}", ps ? ps : "null");
            free(ps);
            cJSON_Delete(pl);
            fclose(f);
            rename(tmp, path);
        }
    }
    pthread_mutex_unlock(&g_lock);
}

static Wrap *make_wrap(const char *uri, const char *payload, LSFilterFunc cb,
                       void *ctx, bool once)
{
    Wrap *w = malloc(sizeof *w);
    w->once = once;
    w->cb = cb;
    w->ctx = ctx;
    w->uri = strdup(uri ? uri : "");
    w->req = strdup(payload ? payload : "");
    return w;
}

/* Les Wrap ne sont libérés que pour les appels à réponse unique : un appel
 * avec abonnement peut recevoir des réponses indéfiniment. */

#define HOOK_CALL(name, oneReply)                                              \
    bool name(LSHandle *sh, const char *uri, const char *payload,              \
              LSFilterFunc cb, void *ctx, LSMessageToken *tok, LSError *err)   \
    {                                                                          \
        static call_fn real;                                                   \
        if (!real)                                                             \
            real = (call_fn)real_sym(#name);                              \
        if (!real)                                                             \
            return false;                                                      \
        if (!cb || t_depth)                                                    \
            return real(sh, uri, payload, cb, ctx, tok, err);                  \
        Wrap *w = make_wrap(uri, payload, cb, ctx, oneReply);                            \
        if (g_log)                                                             \
            logf_("CALL %s %s", w->uri, w->req);                               \
        if (uri && payload)                                                    \
            observe_call(uri, payload);                                        \
        t_depth++;                                                             \
        bool ok = real(sh, uri, payload, wrapped_cb, w, tok, err);             \
        if (!ok && oneReply)                                                   \
            free(w->uri), free(w->req), free(w);                               \
        t_depth--;                                                             \
        return ok;                                                             \
    }

#define HOOK_CALL_APP(name, oneReply)                                          \
    bool name(LSHandle *sh, const char *uri, const char *payload,              \
              const char *app, LSFilterFunc cb, void *ctx, LSMessageToken *tok,\
              LSError *err)                                                    \
    {                                                                          \
        static call_app_fn real;                                               \
        if (!real)                                                             \
            real = (call_app_fn)real_sym(#name);                          \
        if (!real)                                                             \
            return false;                                                      \
        if (!cb || t_depth)                                                    \
            return real(sh, uri, payload, app, cb, ctx, tok, err);             \
        Wrap *w = make_wrap(uri, payload, cb, ctx, oneReply);                            \
        if (g_log)                                                             \
            logf_("CALL %s %s", w->uri, w->req);                               \
        if (uri && payload)                                                    \
            observe_call(uri, payload);                                        \
        t_depth++;                                                             \
        bool ok = real(sh, uri, payload, app, wrapped_cb, w, tok, err);        \
        if (!ok && oneReply)                                                   \
            free(w->uri), free(w->req), free(w);                               \
        t_depth--;                                                             \
        return ok;                                                             \
    }

HOOK_CALL(LSCall, 0)
HOOK_CALL(LSCallOneReply, 1)
HOOK_CALL_APP(LSCallFromApplication, 0)
HOOK_CALL_APP(LSCallFromApplicationOneReply, 1)

__attribute__((constructor)) static void init(void)
{
    const char *d = getenv("HOMEPATCH_DIR");
    snprintf(g_dir, sizeof g_dir, "%s", d && *d ? d : "/media/developer/jellyhome");
    pthread_mutex_lock(&g_lock);
    reload_rules();
    pthread_mutex_unlock(&g_lock);
    logf_("homepatch chargé (pid %d)", (int)getpid());
}
