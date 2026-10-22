"""Fuentes de red y de disco (3.18), modulo puro (sin Qt ni VLC).

- Discos: DVD (con menus, dvdnav), Blu-ray (libbluray) y CD de audio (cdda)
  desde una unidad, como direcciones (MRL) que libVLC abre directamente.
- Recursos compartidos: SMB (Windows/Samba), NFS, SFTP y FTP. libVLC los
  abre con su propio acceso. La URL lleva solo el usuario; la contrasena va
  como opcion del Media (:smb-pwd=..., share_media_options) y vive solo en
  memoria, asi que nunca termina en session.json ni en los recientes.
- Servidores multimedia UPnP/DLNA: los descubre libVLC (modulo "upnp");
  ver sources_dialog.NetworkBrowser.
"""

import ctypes
import string
import sys
import urllib.parse

# (etiqueta, tipo): el tipo es el esquema del MRL.
DISC_KINDS = [("DVD (con menús)", "dvd"), ("Blu-ray", "bluray"), ("CD de audio", "cdda")]
DISC_KIND_VALUES = tuple(kind for _label, kind in DISC_KINDS)
SHARE_PROTOCOLS = [("SMB (carpeta compartida de Windows)", "smb"), ("NFS", "nfs"), ("SFTP", "sftp"), ("FTP", "ftp")]
SHARE_PROTOCOL_VALUES = tuple(value for _label, value in SHARE_PROTOCOLS)
DEFAULT_PORTS = {"smb": 445, "nfs": 2049, "sftp": 22, "ftp": 21}
UPNP_SERVICE = "upnp"

_DRIVE_CDROM = 5


def disc_mrl(kind: str, drive: str, title: int = 0) -> str:
    """MRL de un disco en `drive` ("D:", "D:\\" o "/dev/sr0"): dvd:///D:/,
    bluray:///D:/, cdda:///D:/ (con #titulo/pista si title > 0)."""
    if kind not in DISC_KIND_VALUES:
        raise ValueError(f"tipo de disco desconocido: {kind!r}")
    drive = (drive or "").strip()
    if not drive:
        raise ValueError("falta la unidad")
    if len(drive) >= 2 and drive[1] == ":" and drive[0].isalpha():
        location = f"/{drive[0].upper()}:/"
    else:
        location = drive if drive.startswith("/") else f"/{drive}"
    mrl = f"{kind}://{location}"
    if title > 0:
        mrl += f"#{int(title)}"
    return mrl


def optical_drives(platform: str = sys.platform, drive_type=None) -> list:
    """Las unidades de CD/DVD/Blu-ray de este equipo ("D:"...). En Windows,
    GetDriveTypeW == DRIVE_CDROM; en otros sistemas, una lista vacia (el
    usuario escribe el dispositivo)."""
    if platform != "win32":
        return []
    if drive_type is None:
        get_type = ctypes.windll.kernel32.GetDriveTypeW  # type: ignore[attr-defined]
        drive_type = lambda root: get_type(ctypes.c_wchar_p(root))  # noqa: E731
    return [f"{letter}:" for letter in string.ascii_uppercase if drive_type(f"{letter}:\\") == _DRIVE_CDROM]


def share_url(protocol: str, host: str, path: str = "", user: str = "", port: int = 0) -> str:
    """URL de un recurso compartido: smb://usuario@host/carpeta/... El usuario
    se codifica; la ruta acepta "\\" de Windows y "/". Sin contrasena: ver
    share_media_options()."""
    if protocol not in SHARE_PROTOCOL_VALUES:
        raise ValueError(f"protocolo desconocido: {protocol!r}")
    host = (host or "").strip().strip("/\\")
    if host.startswith("\\\\"):
        host = host[2:]
    if not host:
        raise ValueError("falta el servidor")
    # Una ruta UNC completa en el campo del servidor: \\nas\videos\pelis
    parts = host.replace("\\", "/").split("/", 1)
    host = parts[0]
    path = "/".join(p for p in ((parts[1] if len(parts) > 1 else ""), (path or "").replace("\\", "/")) if p)
    credentials = urllib.parse.quote(user, safe="") + "@" if user else ""
    netloc = host + (f":{int(port)}" if port and int(port) != DEFAULT_PORTS.get(protocol) else "")
    quoted_path = "/".join(urllib.parse.quote(segment) for segment in path.strip("/").split("/") if segment)
    return f"{protocol}://{credentials}{netloc}/{quoted_path}"


# Opciones de acceso de libVLC 3 por protocolo: (usuario, contrasena[, dominio]).
_CREDENTIAL_OPTIONS = {"smb": ("smb-user", "smb-pwd", "smb-domain"), "sftp": ("sftp-user", "sftp-pwd"), "ftp": ("ftp-user", "ftp-pwd")}


def share_media_options(protocol: str, user: str = "", password: str = "", domain: str = "") -> list:
    """Opciones del Media con las credenciales (":smb-user=...", ":smb-pwd=..."). NFS no lleva."""
    names = _CREDENTIAL_OPTIONS.get(protocol)
    if not names:
        return []
    options = []
    if user:
        options.append(f":{names[0]}={user}")
    if password:
        options.append(f":{names[1]}={password}")
    if domain and len(names) > 2:
        options.append(f":{names[2]}={domain}")
    return options


def share_root(url: str) -> str:
    """"esquema://[usuario@]host[:puerto]" de una URL: las credenciales guardadas
    para un servidor valen para cualquier archivo de ese servidor."""
    parsed = urllib.parse.urlsplit(url)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
