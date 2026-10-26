"""Client minimo per l'API REST di OpenWISP (openwisp-users e openwisp-radius).

Tutto passa dal token Bearer di openwisp-users: il programma può fare
esattamente quello che l'utente collegato può fare nell'admin.
"""

from __future__ import annotations

import io
import csv
from dataclasses import dataclass
from datetime import date
from urllib.parse import urljoin, urlparse

import requests

from .i18n import tr

# Sopra questa soglia openwisp-radius crea il batch in background (celery) e
# la risposta non contiene le credenziali: le serie più lunghe le dividiamo.
BATCH_SYNC_MAX = 14


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Credential:
    username: str
    password: str
    user_id: str | None


def normalize_server(url: str) -> str:
    """'openwisp.example.org' -> 'https://openwisp.example.org'."""
    url = url.strip().rstrip("/")
    if not url:
        raise ApiError(tr("Indirizzo del server mancante"))
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ApiError(tr("Il server deve usare HTTPS"))
    if not parsed.netloc:
        raise ApiError(tr("Indirizzo del server non valido"))
    return f"{parsed.scheme}://{parsed.netloc}"


def _error_text(data) -> str:
    """Errori DRF ({"campo": ["messaggio"]}) in una riga leggibile."""
    if isinstance(data, dict):
        parts = []
        for key, value in data.items():
            text = _error_text(value)
            if key in ("detail", "non_field_errors"):
                parts.append(text)
            else:
                parts.append(f"{key}: {text}")
        return "; ".join(parts)
    if isinstance(data, list):
        return " ".join(_error_text(v) for v in data)
    return str(data)


class OpenWispApi:
    def __init__(self, server: str, token: str | None = None, timeout: float = 30):
        self.server = normalize_server(server)
        self.base = self.server + "/api/v1/"
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"

    def _url(self, path: str) -> str:
        return urljoin(self.base, path.lstrip("/"))

    def _request(self, method: str, path_or_url: str, auth: bool = True, **kwargs):
        url = path_or_url if "://" in path_or_url else self._url(path_or_url)
        # i link "next" della paginazione devono restare sullo stesso server
        if urlparse(url).netloc != urlparse(self.server).netloc:
            raise ApiError(tr("Risposta che punta a un altro server"))
        headers = kwargs.pop("headers", {})
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = self.session.request(
                method, url, headers=headers, timeout=self.timeout, **kwargs
            )
        except requests.RequestException as error:
            raise ApiError(tr("Server non raggiungibile: {error}").format(error=error)) from error
        if response.status_code >= 400:
            try:
                message = _error_text(response.json())
            except ValueError:
                message = response.reason or "errore"
            if response.status_code == 401:
                message = tr("Accesso scaduto o non valido: rifai il login")
            elif response.status_code >= 500:
                message = tr("Errore interno del server OpenWISP ({status}): controlla i log del server").format(
                    status=response.status_code)
            elif response.status_code == 403 and not message:
                message = tr("Permesso negato")
            raise ApiError(message, response.status_code)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise ApiError(tr("Risposta del server non valida")) from error

    def _all(self, path: str, params: dict | None = None) -> list:
        data = self._request("GET", path, params=params)
        if isinstance(data, list):
            return data
        out = list(data.get("results", []))
        while data.get("next"):
            data = self._request("GET", data["next"])
            out += data.get("results", [])
        return out

    # --- accesso ---

    def obtain_token(self, username: str, password: str) -> str:
        data = self._request(
            "POST",
            "users/token/",
            auth=False,
            json={"username": username, "password": password},
        )
        token = (data or {}).get("token")
        if not token:
            raise ApiError(tr("Il server non ha restituito il token"))
        self.token = token
        return token

    def current_user(self, username: str) -> dict | None:
        """Non c'è un endpoint "me": si cerca l'utente per nome.

        users/user/ ignora "search" (openwisp-users 1.3): filtriamo noi.
        """
        for user in self._all("users/user/"):
            if user.get("username") == username:
                return user
        return None

    def email_in_use(self, email: str) -> bool:
        """Solo tra gli utenti visibili: un operatore non vede le altre organizzazioni."""
        email = email.strip().lower()
        return any((u.get("email") or "").lower() == email for u in self._all("users/user/"))

    def organizations(self) -> list[dict]:
        """Il superuser le vede tutte, gli altri solo quelle che gestiscono."""
        return self._all("users/organization/")

    def radius_groups(self, organization_id: str) -> list[dict]:
        groups = self._all("radius/group/")
        return [g for g in groups if g.get("organization") == organization_id]

    # --- creazione degli accessi ---

    def create_series(
        self,
        organization_slug: str,
        name: str,
        prefix: str,
        count: int,
        expiration: date,
        group: str | None = None,
        notes: str = "",
    ) -> list[Credential]:
        """Voucher "prefisso1, prefisso2, ..." con password generate dal server."""
        if not 1 <= count <= BATCH_SYNC_MAX:
            raise ValueError("count fuori intervallo")
        data = {
            "strategy": "prefix",
            "organization_slug": organization_slug,
            "name": name,
            "prefix": prefix,
            "number_of_users": count,
            "expiration_date": expiration.isoformat(),
            "notes": notes,
        }
        if group:
            data["group"] = group
        batch = self._request("POST", "radius/batch/", json=data)
        ids = {u["username"]: u.get("id") for u in batch.get("users") or []}
        credentials = batch.get("user_credentials") or []
        if not credentials:
            raise ApiError(tr("Il server non ha restituito le credenziali"))
        return [Credential(u, p, ids.get(u)) for u, p in credentials]

    def create_user(
        self,
        organization_slug: str,
        name: str,
        username: str,
        password: str,
        email: str,
        expiration: date,
        first_name: str = "",
        last_name: str = "",
        group: str | None = None,
        notes: str = "",
    ) -> Credential:
        """Un ospite con nome scelto: batch "csv" di una riga.

        Con "cleartext$" il server usa la nostra password e non manda email.
        """
        # l'email deve essere unica: openwisp-radius 1.3 la rifiuta con un 500
        if self.email_in_use(email):
            raise ApiError(tr("L'email {email} è già usata da un altro utente").format(email=email))
        buffer = io.StringIO()
        csv.writer(buffer).writerow(
            [username, "cleartext$" + password, email, first_name, last_name]
        )
        data = {
            "strategy": "csv",
            "organization_slug": organization_slug,
            "name": name,
            "expiration_date": expiration.isoformat(),
            "notes": notes,
        }
        if group:
            data["group"] = group
        files = {"csvfile": ("utente.csv", buffer.getvalue().encode(), "text/csv")}
        try:
            batch = self._request("POST", "radius/batch/", data=data, files=files)
        except ApiError as error:
            # email usata in un'organizzazione che non vediamo: anche qui un 500
            if error.status and error.status >= 500:
                raise ApiError(tr("OpenWISP non ha creato l'ospite ({status}): di solito "
                                  "l'email è già usata da un altro utente").format(
                    status=error.status), error.status) from error
            raise
        users = batch.get("users") or []
        if len(users) != 1:
            raise ApiError(tr("Utente {username} non creato").format(username=username))
        # se il nome è già preso il server aggiunge un numero (pippo -> pippo1)
        return Credential(users[0]["username"], password, users[0].get("id"))

    # --- gestione ---

    def user(self, user_id: str) -> dict:
        return self._request("GET", f"users/user/{user_id}/")

    def set_active(self, user_id: str, active: bool) -> dict:
        return self._request(
            "PATCH", f"users/user/{user_id}/", json={"is_active": active}
        )
