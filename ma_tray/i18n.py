"""Tiny translation table: French when the desktop locale is French, English otherwise."""

from __future__ import annotations

import locale
import os

_FR = {
    "Offline": "Hors ligne",
    "Connecting…": "Connexion…",
    "Not configured": "Non configuré",
    "Connect": "Connexion",
    "Settings…": "Paramètres…",
    "Quit": "Quitter",
    "Play": "Lecture",
    "Pause": "Pause",
    "Stop": "Stop",
    "Volume up": "Volume +",
    "Volume down": "Volume −",
    "Next track": "Piste suivante",
    "Previous track": "Piste précédente",
    "Player": "Lecteur",
    "Open Music Assistant": "Ouvrir Music Assistant",
    "Nothing playing": "Aucune lecture",
    "No player available": "Aucun lecteur disponible",
    "volume": "volume",
    "muted": "muet",
    # settings window
    "Music Assistant settings": "Paramètres Music Assistant",
    "Server URL": "URL du serveur",
    "Token": "Jeton",
    "Show token": "Afficher le jeton",
    "Default player": "Lecteur par défaut",
    "Automatic": "Automatique",
    "Show volume next to the icon": "Afficher le volume à côté de l'icône",
    "Timeout (s)": "Délai d'attente (s)",
    "Test": "Tester",
    "Cancel": "Annuler",
    "Save": "Enregistrer",
    "Testing…": "Test en cours…",
    "Connected to {name}: {count} player(s)": "Connecté à {name} : {count} lecteur(s)",
    "Server": "Serveur",
    "Behaviour": "Comportement",
    "Create a long-lived token in the Music Assistant web UI (your profile).":
        "Créez un jeton longue durée dans l'interface web de Music Assistant (votre profil).",
    "Paired server: {id}": "Serveur associé : {id}",
    "Not paired yet (done at the first successful connection)":
        "Pas encore associé (fait à la première connexion réussie)",
    "Forget": "Oublier",
    # errors
    "Server unreachable": "Serveur injoignable",
    "Server not answering": "Le serveur ne répond pas",
    "Invalid token": "Jeton invalide",
    "Different server at this address: token not sent": "Serveur différent à cette adresse : jeton non envoyé",
    "URL and token are required": "L'URL et le jeton sont obligatoires",
    "Offline: use Connect in the menu": "Hors ligne : utilisez « Connexion » dans le menu",
    "ma-tray is not running": "ma-tray n'est pas lancé",
    "Command failed": "Échec de la commande",
}


def _is_french() -> bool:
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return value.lower().startswith("fr")
    try:
        return (locale.getlocale()[0] or "").lower().startswith("fr")
    except ValueError:
        return False


_TABLE = _FR if _is_french() else {}


def _(text: str, **kwargs: object) -> str:
    out = _TABLE.get(text, text)
    return out.format(**kwargs) if kwargs else out
