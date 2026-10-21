"""getpass minimal : le Python de la TV n'a pas ce module, que yt-dlp importe."""


def getpass(prompt="Password: ", stream=None):
    return ""


def getuser():
    return "root"
