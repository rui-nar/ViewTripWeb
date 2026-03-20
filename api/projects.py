"""REST projects endpoints — list, create, open, delete projects.

Routes:
    GET    /api/projects/          — list saved projects for current user
    POST   /api/projects/          — create new project
    GET    /api/projects/{name}    — get project data (GeoJSON + metadata)
    DELETE /api/projects/{name}    — delete a project
    POST   /api/projects/import    — upload a .gettracks file
"""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from api.deps import get_current_user
from src.project.io import ProjectIO

router = APIRouter(prefix="/api/projects", tags=["projects"])

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _projects_dir(user_id: str) -> str:
    path = os.path.join(_DATA_DIR, "users", user_id, "projects")
    os.makedirs(path, exist_ok=True)
    return path


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
def list_projects(current_user: Annotated[dict, Depends(get_current_user)]):
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    projects = []
    for fname in sorted(os.listdir(pdir)):
        if fname.endswith(ProjectIO.EXTENSION):
            projects.append({
                "name": fname[: -len(ProjectIO.EXTENSION)],
                "filename": fname,
            })
    return projects


class CreateProjectRequest(BaseModel):
    name: str


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_project(
    body: CreateProjectRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    name = body.name.strip() or "My Trip"
    path = os.path.join(pdir, name + ProjectIO.EXTENSION)
    if os.path.exists(path):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project '{name}' already exists",
        )
    project = ProjectIO.new(name)
    ProjectIO.save(project, path)
    return {"name": name, "filename": name + ProjectIO.EXTENSION}


@router.get("/{name}")
def get_project(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    path = os.path.join(pdir, name + ProjectIO.EXTENSION)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    project = ProjectIO.load(path)
    return ProjectIO.to_dict(project)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    path = os.path.join(pdir, name + ProjectIO.EXTENSION)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    os.remove(path)


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_project(
    file: Annotated[UploadFile, File()],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    fname = os.path.basename(file.filename or "imported.gettracks")
    if not fname.endswith(ProjectIO.EXTENSION):
        fname += ProjectIO.EXTENSION
    dest = os.path.join(pdir, fname)
    contents = await file.read()
    with open(dest, "wb") as fh:
        fh.write(contents)
    return {"name": fname[: -len(ProjectIO.EXTENSION)], "filename": fname}
