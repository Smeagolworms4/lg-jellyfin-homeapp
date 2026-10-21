# JellyHome

Ton serveur Jellyfin sur l'écran d'accueil des TV LG webOS : le grand carrousel du
haut, le bandeau et des rangées montrent tes films et séries, avec leurs visuels, et
un clic ouvre la fiche dans l'app Jellyfin.

**TV rootée requise** (Homebrew Channel). Testé sur webOS 10.3.

![Accueil : le carrousel du haut avec une série Jellyfin](docs/accueil.jpg)

| Bande-annonce lue dans le carrousel | Rangées Jellyfin |
|---|---|
| ![Bande-annonce](docs/bande-annonce.jpg) | ![Rangées](docs/rangees.jpg) |

## Ce que ça fait

- **Carrousel du haut**, à la place des pubs LG :
  - le contenu choisi dans « Zone du haut » (reprendre, à suivre, derniers ajouts,
    favoris, à découvrir…) ;
  - chaque élément a son visuel composé sur la TV : l'affiche à gauche, l'image de
    fond à droite, et le logo du titre en haut à droite (à défaut, son nom en gros) ;
  - **bandes-annonces** : celles de Jellyfin, sinon les liens YouTube de ses
    métadonnées. Elles sont téléchargées à l'avance (480p, sinon 720p, sinon 1080p)
    et lues par-dessus l'affiche. L'accueil met le son quand on est dessus.
- **Bandeau** à côté des entrées récentes et **rangée** en dessous : une catégorie
  Jellyfin, ou le contenu LG d'origine.
- **Rangées** Reprendre, À suivre, Derniers ajouts, avec barre de progression.
- **Pubs LG masquées** (au choix).
- **Clic** sur un élément : l'app Jellyfin s'ouvre sur sa fiche.

Les réglages se font dans l'app JellyHome. La connexion au serveur passe par Quick
Connect : aucun mot de passe à taper.

## Installation

Installe l'IPK d'une release avec le Homebrew Channel. Ouvre JellyHome une fois : l'app pose le démarrage automatique et active le
patch de l'accueil. Connecte-toi avec Quick Connect, puis « Appliquer à l'accueil ».

Depuis les sources, sur une TV rootée accessible en SSH (root, par clé) :

```sh
sh tools/package.sh          # construit dist/<id>_<version>_all.ipk
sh tools/install.sh [IP]     # l'installe sur la TV (défaut 192.168.0.221)
```

`tools/build.sh` (lancé par `package.sh`) compile le shim pour la TV dans Docker
(armv7, glibc 2.35).

## Fonctionnement

L'accueil webOS est une app Flutter compilée : on ne la modifie pas. On s'intercale
entre elle et le bus luna.

- **`shim/homepatch.c`** → `libhomepatch.so`, chargé dans l'accueil par
  `LD_PRELOAD`. Il intercepte les appels luna et réécrit leurs réponses selon
  `rules.json` : réponse remplacée, fusionnée ou retouchée champ par champ, relue à
  chaud. Il peut aussi copier un appel sortant dans un fichier (clics). Sans règle
  applicable, tout passe tel quel.
- **`app/root/flutter-client`** est monté (bind-mount, en RAM) par-dessus
  `/usr/bin/flutter-client`. Il ajoute le shim au seul lancement de l'accueil, avec un
  garde-fou : trois plantages en une minute coupent le patch.
- **`app/root/jellyfeed.py`**, le service, tourne sur la TV :
  - il interroge Jellyfin et écrit les réponses toutes faites et `rules.json` ;
  - il prépare en tâche de fond les visuels et les bandes-annonces du carrousel ;
  - il les sert en HTTP sur `127.0.0.1:8097`, car l'accueil ne lit pas les fichiers
    locaux ;
  - il ouvre la fiche Jellyfin après un clic.
- **`app/root/jellyhomectl.sh`** démarre et arrête le tout : installation, hook de
  démarrage, relance de l'accueil.
- **`app/`** contient l'app de réglages (HTML/JS). Elle passe ses commandes root par
  le Homebrew Channel.

Le carrousel du haut est l'emplacement pub `Portal/HomeBigCarousel@Main` du
gestionnaire de pub. Une pub vidéo y est un couple d'actifs, la vidéo et une image
pleine largeur, et la vidéo occupe les 46 % de gauche.

La TV n'a ni Pillow ni ffmpeg, et son Python est amputé. Il faut donc tout faire en
Python pur :
- décodage et encodage PNG, et composition des visuels ;
- texte dessiné à partir de glyphes pré-rendus : `tools/make-font.py`, Noto Sans Bold
  (licence OFL), produit `app/root/font-*` ;
- bandes-annonces YouTube récupérées par yt-dlp, téléchargé au premier besoin. yt-dlp
  passe les vérifications de YouTube avec le Node.js de webOS. Les modules Python
  manquants sont dans `app/root/pylib`, avec `xml` repris de CPython (licence PSF) ;
- vidéo et son DASH réunis sans réencodage (`mux_fmp4`).

Les données vivent dans `/media/developer/jellyhome` : `config.json` (session Jellyfin,
lisible par root seulement), règles, réponses, cache du carrousel (`ad/`). L'interception
tient en montages effacés à chaque redémarrage. Hors du hook de démarrage, rien n'est
écrit dans le système.

## Désinstaller

Dans l'app : « Désactiver le patch ». En SSH :

```sh
/media/developer/apps/usr/palm/applications/com.smeagolworms4.jellyhome/root/jellyhomectl.sh uninstall
```

Puis désinstalle l'app depuis le Homebrew Channel.

## Développement

Le code a été écrit avec l'aide de Claude (Anthropic). Il a été entièrement relu et
testé par l'auteur, sur une vraie TV LG (webOS 10.3).

## Licence

MIT, voir [LICENSE](LICENSE). Composants tiers : cJSON (`shim/vendor`, MIT),
`app/root/pylib/xml` (CPython, licence PSF), police Noto Sans Bold pré-rendue
(`app/root/font-*`, licence OFL). yt-dlp (Unlicense) est téléchargé par la TV, pas
fourni.
