# P08 - Widgets: Mac monitoring

Status: ready-for-agent
Blocked by: P02

## Scope

- CPU, GPU (Apple silicon where macOS exposes it), RAM, disks, network, ping; charts; top processes (view only, no killing in wave 1).
- Collector: start in Python (psutil). Measure its CPU cost at a 1 s interval; if it is heavy, write a small Go sidecar that pushes JSON to the Brain over a local socket. Record the measurement in the issue.
- Emit a Signal when the Mac is under sustained heavy load (Expression only, not speech).

## Acceptance criteria

- [ ] Stats update about once per second on a Panel.
- [ ] The collector's own CPU cost is measured and written down; the Go sidecar exists only if justified.
