"""Reflex app state — wraps GetTracks business logic."""
import os
import reflex as rx

from src.config.settings import Config
from src.project.project_io import ProjectIO
from src.models.project import Project
from src.auth.oauth import OAuth2Session
from src.auth.token_store import TokenStore
from src.api.strava_client import StravaAPI
from src.cache.activity_cache import ActivityCache
from src.gpx.processor import GPXProcessor, ExportOptions

DATA_DIR = os.environ.get("GETTRACKS_DATA_DIR", os.path.join(os.path.expanduser("~"), ".config", "GetTracks"))
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "config.json")

# Override TokenStore path to use DATA_DIR volume
TokenStore._TOKEN_DIR = type("_P", (), {"__truediv__": lambda s, p: __import__("pathlib").Path(DATA_DIR) / p})()
TokenStore._TOKEN_DIR = __import__("pathlib").Path(DATA_DIR)
TokenStore._TOKEN_FILE = __import__("pathlib").Path(DATA_DIR) / "tokens.json"

_config = Config(CONFIG_FILE)
_cache = ActivityCache(os.path.join(DATA_DIR, "cache"))

USER_ID = "default"


class ProjectState(rx.State):
    """Manages the open project."""

    project_name: str = ""
    project_path: str = ""
    is_dirty: bool = False
    item_names: list[str] = []

    _project: Project = None

    def new_project(self, name: str):
        self._project = Project(name=name)
        self.project_name = name
        self.project_path = ""
        self.is_dirty = False
        self.item_names = []

    def save_project(self, path: str = ""):
        if not self._project:
            return
        save_path = path or self.project_path
        if not save_path:
            return
        ProjectIO.save(self._project, save_path)
        self.project_path = save_path
        self.is_dirty = False

    def open_project(self, path: str):
        self._project = ProjectIO.load(path)
        self.project_name = self._project.name
        self.project_path = path
        self.is_dirty = False
        self._refresh_item_list()

    def reorder_item(self, from_idx: int, to_idx: int):
        if self._project:
            self._project.move_item(from_idx, to_idx)
            self.is_dirty = True
            self._refresh_item_list()

    def remove_item(self, idx: int):
        if self._project:
            self._project.remove_item(idx)
            self.is_dirty = True
            self._refresh_item_list()

    def _refresh_item_list(self):
        if not self._project:
            self.item_names = []
            return
        names = []
        for item in self._project.items:
            if item.activity_id:
                act = self._project.activity_by_id(item.activity_id)
                names.append(act.name if act else f"Activity {item.activity_id}")
            elif item.segment:
                names.append(f"[{item.segment.transport_type}] segment")
        self.item_names = names


class StravaState(rx.State):
    """Manages Strava auth and activity import."""

    is_authenticated: bool = False
    auth_url: str = ""
    activities: list[dict] = []
    is_loading: bool = False
    error_message: str = ""

    def on_load(self):
        token = TokenStore.load_token(USER_ID)
        self.is_authenticated = token is not None

    def start_oauth(self):
        oauth = OAuth2Session(_config)
        self.auth_url = oauth.authorization_url(scope="activity:read_all")

    def handle_callback(self, code: str):
        if not code:
            return
        oauth = OAuth2Session(_config)
        token = oauth.exchange_code(code)
        TokenStore.save_token(USER_ID, token)
        self.is_authenticated = True
        self.auth_url = ""
        return rx.redirect("/")

    @rx.background
    async def fetch_activities(self):
        async with self:
            self.is_loading = True
            self.error_message = ""
        try:
            api = StravaAPI(_config, USER_ID)
            raw = api.get_activities(per_page=100)
            cached = _cache.merge(raw)
            _cache.save(cached)
            async with self:
                self.activities = [
                    {
                        "id": str(a.id),
                        "name": a.name,
                        "type": a.sport_type,
                        "date": str(a.start_date_local)[:10],
                    }
                    for a in cached
                ]
        except Exception as exc:
            async with self:
                self.error_message = str(exc)
        finally:
            async with self:
                self.is_loading = False


class ExportState(rx.State):
    """Manages GPX preview and export."""

    export_status: str = ""

    def export_gpx(self, output_path: str):
        project = ProjectState.get_state(self)._project
        if not project:
            self.export_status = "No project open."
            return
        options = ExportOptions()
        processor = GPXProcessor()
        gpx = processor.merge([], options)  # TODO: pass full Track list
        os.makedirs(os.path.join(DATA_DIR, "exports"), exist_ok=True)
        processor.save(gpx, output_path)
        self.export_status = f"Exported to {output_path}"
        return rx.download(url=f"/api/exports/{os.path.basename(output_path)}")
