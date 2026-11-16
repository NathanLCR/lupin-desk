"""Ponte somente leitura com o workspace Cowork (`state/*.yaml`)."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_ALLOWED_STATE_FILES = frozenset({"tasks.yaml", "deadlines.yaml", "schedule.yaml"})


class CoworkError(Exception):
    """Erro controlado nas operações de leitura do Cowork."""


class CoworkStore:
    """Leitura confinada em `COWORK_WORKSPACE_PATH/state/` (somente leitura)."""

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = Path(workspace_path).expanduser()

    @property
    def state_dir(self) -> Path:
        return self.workspace_path / "state"

    def _resolve_state_file(self, filename: str) -> Path:
        if filename not in _ALLOWED_STATE_FILES:
            raise CoworkError(f"Arquivo de estado não permitido: {filename}")
        state_root = self.state_dir.resolve()
        candidate = (self.state_dir / filename).resolve()
        if candidate.parent != state_root:
            raise CoworkError("Caminho fora de Cowork/state/ bloqueado por segurança.")
        return candidate

    def _read_yaml_raw(self, filename: str) -> tuple[str, Any]:
        target = self._resolve_state_file(filename)
        if not target.exists():
            default_data: Any = {"week_of": "", "shifts": []} if filename == "schedule.yaml" else []
            return "", default_data
        raw_text = target.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw_text)
        if parsed is None:
            parsed = {"week_of": "", "shifts": []} if filename == "schedule.yaml" else []
        return raw_text, parsed

    def load_state(self) -> dict[str, Any]:
        """Carrega `tasks.yaml`, `deadlines.yaml` e `schedule.yaml` com status de saúde."""
        ws_exists = self.workspace_path.exists() and self.state_dir.exists()
        if not ws_exists:
            return {
                "workspace_exists": False,
                "workspace_path": str(self.workspace_path),
                "sync_status": "red",
                "sync_message": "Workspace Cowork não encontrado.",
                "tasks": [],
                "deadlines": [],
                "schedule": {"week_of": "", "shifts": []},
                "open_tasks_count": 0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        try:
            _, tasks_raw = self._read_yaml_raw("tasks.yaml")
            _, deadlines_raw = self._read_yaml_raw("deadlines.yaml")
            _, schedule_raw = self._read_yaml_raw("schedule.yaml")
        except (CoworkError, yaml.YAMLError, OSError) as exc:
            return {
                "workspace_exists": True,
                "workspace_path": str(self.workspace_path),
                "sync_status": "red",
                "sync_message": f"Erro ao ler YAML do Cowork: {exc}",
                "tasks": [],
                "deadlines": [],
                "schedule": {"week_of": "", "shifts": []},
                "open_tasks_count": 0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        deadlines = deadlines_raw if isinstance(deadlines_raw, list) else []
        schedule = schedule_raw if isinstance(schedule_raw, dict) else {"week_of": "", "shifts": []}
        if not isinstance(schedule.get("shifts"), list):
            schedule["shifts"] = []

        open_count = sum(1 for t in tasks if isinstance(t, dict) and t.get("status") == "open")
        missing_files = [f for f in _ALLOWED_STATE_FILES if not (self.state_dir / f).exists()]
        sync_status = "yellow" if missing_files else "green"
        sync_message = (
            f"Arquivos ausentes: {', '.join(sorted(missing_files))}"
            if missing_files
            else "Cowork state sincronizado"
        )

        return {
            "workspace_exists": True,
            "workspace_path": str(self.workspace_path),
            "sync_status": sync_status,
            "sync_message": sync_message,
            "tasks": tasks,
            "deadlines": deadlines,
            "schedule": schedule,
            "open_tasks_count": open_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def build_prompt_context(self, max_tasks: int = 12, max_deadlines: int = 6) -> str:
        """Gera um resumo compacto do estado Cowork para injeção no system prompt do chat."""
        state = self.load_state()
        if not state.get("workspace_exists"):
            return ""

        lines: list[str] = []
        open_tasks = [
            t for t in (state.get("tasks") or []) if isinstance(t, dict) and t.get("status") == "open"
        ]
        if open_tasks:
            lines.append(f"Tarefas abertas ({len(open_tasks)} no total):")
            for t in open_tasks[:max_tasks]:
                tid = t.get("id", "?")
                title = str(t.get("title") or "").strip()
                due = str(t.get("due") or "").strip()
                due_txt = f" [vence {due}]" if due else ""
                lines.append(f"- {tid}: {title}{due_txt}")

        deadlines = [d for d in (state.get("deadlines") or []) if isinstance(d, dict)]
        if deadlines:
            lines.append("Prazos (deadlines):")
            for d in deadlines[:max_deadlines]:
                did = d.get("id", "?")
                title = str(d.get("title") or "").strip()
                d_date = str(d.get("date") or "").strip()
                hard = " (FIXO)" if d.get("hard") else ""
                lines.append(f"- {did}: {title} em {d_date}{hard}")

        shifts = (state.get("schedule") or {}).get("shifts") or []
        if shifts:
            lines.append("Turnos da semana:")
            for s in shifts[:7]:
                if isinstance(s, dict):
                    lines.append(
                        f"- {s.get('date', '?')} {s.get('start', '?')}-{s.get('end', '?')} ({s.get('place', '?')})"
                    )

        return "\n".join(lines)



def get_git_sync_status(workspace_path: Path) -> dict[str, Any]:
    """Consulta `git status --porcelain -b` no Cowork para alimentar o LED de Sync."""
    ws = Path(workspace_path).expanduser()
    if not (ws / ".git").exists():
        return {
            "ok": False,
            "sync_status": "red",
            "branch": "",
            "dirty_count": 0,
            "summary": "Repositório Git não encontrado no Cowork.",
        }
    try:
        proc = subprocess.run(
            ["/usr/bin/git", "-C", str(ws), "status", "--porcelain", "-b"],
            shell=False,
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "sync_status": "red",
                "branch": "",
                "dirty_count": 0,
                "summary": proc.stderr.strip() or "Falha ao consultar git status.",
            }
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        branch_line = lines[0][3:].strip() if lines and lines[0].startswith("## ") else "main"
        dirty_lines = lines[1:] if lines and lines[0].startswith("## ") else lines
        dirty_count = len(dirty_lines)
        status = "yellow" if dirty_count > 0 else "green"
        return {
            "ok": True,
            "sync_status": status,
            "branch": branch_line,
            "dirty_count": dirty_count,
            "dirty_files": dirty_lines[:20],
            "summary": f"{branch_line} ({dirty_count} alterações locais)" if dirty_count else f"{branch_line} limpo",
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "sync_status": "red",
            "branch": "",
            "dirty_count": 0,
            "summary": str(exc),
        }
