from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, Field

from ...models.table_def import TableDefinition, ColumnDefinition, IndexDefinition


@dataclass
class DockerParams:
    image: Optional[str] = None
    container_name: Optional[str] = None
    env_vars: Optional[dict[str, str]] = None
    volumes: Optional[list[dict[str, str]]] = None


class DockerInfo(BaseModel):
    id: int
    deployment_id: str
    version: str
    host: str
    url: Optional[str] = None
    pid: Optional[int] = None
    whl_path: Optional[str] = None
    package_name: Optional[str] = None
    template_file: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    data: Optional[dict[str, Any]] = None

    class Config:
        from_attributes = True


class DockerCreate(BaseModel):
    deployment_id: str
    version: str
    host: str
    url: Optional[str] = None
    pid: Optional[int] = None
    whl_path: Optional[str] = None
    package_name: Optional[str] = None
    template_file: Optional[str] = None
    data: Optional[dict[str, Any]] = None


DOCKER_TABLE_DEF = TableDefinition(
    table_name="docker",
    columns=[
        ColumnDefinition("id", "integer", primary_key=True, autoincrement=True),
        ColumnDefinition("deployment_id", "string", length=64, unique=True, nullable=False),
        ColumnDefinition("version", "string", length=32, nullable=False),
        ColumnDefinition("host", "string", length=255, nullable=False),
        ColumnDefinition("url", "string", length=512, nullable=True),
        ColumnDefinition("pid", "integer", nullable=True),
        ColumnDefinition("whl_path", "string", length=512, nullable=True),
        ColumnDefinition("package_name", "string", length=255, nullable=True),
        ColumnDefinition("template_file", "string", length=512, nullable=True),
        ColumnDefinition("created_at", "datetime", nullable=False),
        ColumnDefinition("updated_at", "datetime", nullable=False),
        ColumnDefinition("data", "json", nullable=True),
    ],
    indexes=[
        IndexDefinition(["deployment_id"], unique=True),
    ],
)
