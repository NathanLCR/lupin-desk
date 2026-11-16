"""Ponte segura com o workspace Cowork (`state/*.yaml`, `.backup/` e `app/actions.yaml`)."""

from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_ALLOWED_STATE_FILES = frozenset({"tasks.yaml", "deadlines.yaml", "schedule.yaml"})
_TASK_ID_RE = re.compile(r"^t-(\d+)$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_HM_RE = re.compile(r"^\d{2}:\d{2}$")


class CoworkError(Exception):
    """Erro controlado nas operações de leitura/escrita do Cowork."""


class CoworkStore:
    """Leitura e escrita confinada em `COWORK_WORKSPACE_PATH/state/` com diff e `.backup/`."""

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = Path(workspace_path).expanduser()
        self._pending_captures: dict[str, dict[str, Any]] = {}

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

    def preview_capture(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Prepara uma mutação em `state/*.yaml` e retorna o unified diff sem gravar em disco."""
        if not self.state_dir.exists():
            raise CoworkError("Diretório Cowork/state/ não encontrado.")

        op = (kind or "").strip().lower()
        if op in {"add_task", "complete_task", "reopen_task"}:
            filename = "tasks.yaml"
            raw_before, data = self._read_yaml_raw(filename)
            tasks: list[dict[str, Any]] = list(data) if isinstance(data, list) else []

            if op == "add_task":
                title = str(payload.get("title") or "").strip()
                if not title:
                    raise CoworkError("Título da tarefa é obrigatório.")
                domain = str(payload.get("domain") or "personal").strip() or "personal"
                due = str(payload.get("due") or "").strip()
                if due and not _ISO_DATE_RE.match(due):
                    raise CoworkError("Data `due` deve estar no formato YYYY-MM-DD.")
                next_id = self._next_task_id(tasks)
                new_item: dict[str, Any] = {
                    "id": next_id,
                    "title": title,
                    "domain": domain,
                    "status": "open",
                }
                if due:
                    new_item["due"] = due
                new_item["source"] = "desk-assistant/capture"
                tasks.append(new_item)
                summary = f"Adicionar tarefa {next_id}: {title}"
            else:
                task_id = str(payload.get("id") or "").strip()
                if not task_id:
                    raise CoworkError("ID da tarefa é obrigatório.")
                target_status = "done" if op == "complete_task" else "open"
                found = False
                for item in tasks:
                    if isinstance(item, dict) and str(item.get("id")) == task_id:
                        item["status"] = target_status
                        found = True
                        break
                if not found:
                    raise CoworkError(f"Tarefa '{task_id}' não encontrada em tasks.yaml.")
                verb = "Concluir" if target_status == "done" else "Reabrir"
                summary = f"{verb} tarefa {task_id}"

            rendered_after = self._dump_yaml(tasks, header_from=raw_before)
        elif op == "add_shift":
            filename = "schedule.yaml"
            raw_before, data = self._read_yaml_raw(filename)
            schedule: dict[str, Any] = (
                dict(data) if isinstance(data, dict) else {"week_of": "", "shifts": []}
            )
            shifts = list(schedule.get("shifts") or [])

            shift_date = str(payload.get("date") or "").strip()
            start = str(payload.get("start") or "").strip()
            end = str(payload.get("end") or "").strip()
            place = str(payload.get("place") or "").strip()
            if not _ISO_DATE_RE.match(shift_date):
                raise CoworkError("Data do turno deve estar no formato YYYY-MM-DD.")
            if not (_TIME_HM_RE.match(start) and _TIME_HM_RE.match(end)):
                raise CoworkError("Horários `start` e `end` devem estar no formato HH:MM.")
            if not place:
                raise CoworkError("Local (`place`) do turno é obrigatório.")
            if payload.get("week_of"):
                week_of = str(payload["week_of"]).strip()
                if not _ISO_DATE_RE.match(week_of):
                    raise CoworkError("`week_of` deve estar no formato YYYY-MM-DD.")
                schedule["week_of"] = week_of

            shifts.append({"date": shift_date, "start": start, "end": end, "place": place})
            schedule["shifts"] = shifts
            summary = f"Adicionar turno {shift_date} {start}-{end} ({place})"
            rendered_after = self._dump_yaml(schedule, header_from=raw_before)
        else:
            raise CoworkError(f"Operação de captura não suportada: {kind}")

        diff_lines = list(
            difflib.unified_diff(
                raw_before.splitlines(keepends=True),
                rendered_after.splitlines(keepends=True),
                fromfile=f"a/state/{filename}",
                tofile=f"b/state/{filename}",
            )
        )
        diff_text = "".join(diff_lines) or "(sem alterações)"

        approval_id = uuid.uuid4().hex[:12]
        if len(self._pending_captures) > 50:
            oldest = next(iter(self._pending_captures))
            self._pending_captures.pop(oldest, None)

        self._pending_captures[approval_id] = {
            "filename": filename,
            "content": rendered_after,
            "summary": summary,
            "diff": diff_text,
        }

        return {
            "ok": True,
            "approval_id": approval_id,
            "target_file": f"state/{filename}",
            "summary": summary,
            "diff": diff_text,
            "risk": "write",
        }

    def apply_capture(self, approval_id: str) -> dict[str, Any]:
        """Aplica uma captura previamente revisada, salvando backup em `state/.backup/`."""
        pending = self._pending_captures.pop(approval_id, None)
        if pending is None:
            raise CoworkError("Aprovação expirada ou não encontrada.")

        filename = pending["filename"]
        target = self._resolve_state_file(filename)
        backup_dir = (self.state_dir / ".backup").resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)

        backup_path: Path | None = None
        if target.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            backup_path = backup_dir / f"{stamp}-{filename}"
            shutil.copy2(target, backup_path)

        tmp_target = target.with_suffix(".yaml.tmp")
        tmp_target.write_text(pending["content"], encoding="utf-8")
        os.replace(tmp_target, target)

        return {
            "ok": True,
            "target_file": f"state/{filename}",
            "summary": pending["summary"],
            "backup_path": str(backup_path) if backup_path else None,
        }

    @staticmethod
    def _next_task_id(tasks: list[dict[str, Any]]) -> str:
        max_num = 0
        for item in tasks:
            if not isinstance(item, dict):
                continue
            match = _TASK_ID_RE.match(str(item.get("id") or ""))
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"t-{max_num + 1:03d}"

    @staticmethod
    def _dump_yaml(data: Any, header_from: str = "") -> str:
        header_lines: list[str] = []
        for line in header_from.splitlines():
            if line.startswith("#"):
                header_lines.append(line)
            else:
                break
        body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
        if header_lines:
            return "\n".join(header_lines) + "\n\n" + body
        return body


class ActionsRunner:
    """Executor seguro para `Cowork/app/actions.yaml` com distinção de risco read/write."""

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = Path(workspace_path).expanduser()
        self._pending_actions: dict[str, dict[str, Any]] = {}

    @property
    def manifest_path(self) -> Path:
        return self.workspace_path / "app" / "actions.yaml"

    def list_actions(self) -> list[dict[str, Any]]:
        if not self.manifest_path.exists():
            return []
        try:
            raw = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            return []
        items = raw.get("actions", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
        valid: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            action_id = str(item.get("id") or "").strip()
            argv = item.get("argv")
            if not action_id or not isinstance(argv, list) or not argv:
                continue
            risk = str(item.get("risk") or "write").strip().lower()
            if risk not in {"read", "write", "external"}:
                risk = "write"
            valid.append(
                {
                    "id": action_id,
                    "title": str(item.get("title") or action_id),
                    "domain": str(item.get("domain") or "core"),
                    "cwd": str(item.get("cwd") or "."),
                    "argv": [str(part) for part in argv],
                    "risk": risk,
                    "timeout_s": int(item.get("timeout_s") or 30),
                    "params": item.get("params") if isinstance(item.get("params"), list) else [],
                    "description": str(item.get("description") or ""),
                }
            )
        return valid

    def prepare_run(self, action_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        action = next((a for a in self.list_actions() if a["id"] == action_id), None)
        if action is None:
            raise CoworkError(f"Ação '{action_id}' não encontrada no manifesto.")

        resolved_argv = self._substitute_params(action["argv"], params or {})
        resolved_cwd = (self.workspace_path / action["cwd"]).resolve()
        ws_root = self.workspace_path.resolve()
        if resolved_cwd != ws_root and ws_root not in resolved_cwd.parents:
            raise CoworkError("Diretório de trabalho (`cwd`) fora do workspace Cowork.")

        if action["risk"] == "read":
            return self._execute_argv(action, resolved_argv, resolved_cwd)

        approval_id = uuid.uuid4().hex[:12]
        if len(self._pending_actions) > 50:
            oldest = next(iter(self._pending_actions))
            self._pending_actions.pop(oldest, None)
        self._pending_actions[approval_id] = {
            "action": action,
            "argv": resolved_argv,
            "cwd": resolved_cwd,
        }
        return {
            "ok": True,
            "executed": False,
            "requires_approval": True,
            "approval_id": approval_id,
            "action_id": action["id"],
            "title": action["title"],
            "risk": action["risk"],
            "diff": f"Comando: {' '.join(resolved_argv)}\nCwd: {resolved_cwd}",
        }

    def apply_action(self, approval_id: str) -> dict[str, Any]:
        pending = self._pending_actions.pop(approval_id, None)
        if pending is None:
            raise CoworkError("Aprovação de ação expirada ou não encontrada.")
        return self._execute_argv(pending["action"], pending["argv"], pending["cwd"])

    @staticmethod
    def _substitute_params(argv: list[str], params: dict[str, Any]) -> list[str]:
        rendered: list[str] = []
        for token in argv:
            out = token
            for key, val in params.items():
                placeholder = "{" + str(key) + "}"
                if placeholder in out:
                    clean_val = str(val).strip()
                    if ".." in clean_val or "\n" in clean_val or "\r" in clean_val:
                        raise CoworkError(f"Parâmetro inválido para '{key}'.")
                    out = out.replace(placeholder, clean_val)
            if "{" in out and "}" in out:
                raise CoworkError(f"Parâmetro obrigatório ausente em '{out}'.")
            rendered.append(out)
        return rendered

    @staticmethod
    def _execute_argv(action: dict[str, Any], argv: list[str], cwd: Path) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                argv,
                cwd=str(cwd),
                shell=False,
                capture_output=True,
                text=True,
                timeout=max(1, min(int(action.get("timeout_s") or 30), 120)),
                check=False,
            )
            return {
                "ok": proc.returncode == 0,
                "executed": True,
                "action_id": action["id"],
                "title": action["title"],
                "risk": action["risk"],
                "exit_code": proc.returncode,
                "stdout": proc.stdout[-8000:],
                "stderr": proc.stderr[-4000:],
            }
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                "ok": False,
                "executed": True,
                "action_id": action["id"],
                "title": action["title"],
                "risk": action["risk"],
                "exit_code": -1,
                "stdout": "",
                "stderr": str(exc),
            }


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
