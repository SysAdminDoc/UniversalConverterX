# Local Prometheus and Grafana

`ucx serve` exposes Prometheus text-format metrics at
`http://127.0.0.1:17654/metrics`. The listener is loopback-only and requires
the bearer token printed by `ucx serve`; UCX does not send metrics anywhere,
run a telemetry agent, or require Prometheus/Grafana.

1. Start the local API: `ucx serve --port 17654` and retain the printed token.
2. Add that token as an `Authorization: Bearer <token>` header in the
   `prometheus.yml` scrape configuration, then reload Prometheus.
3. Copy the remaining `scrape_configs` entry from `prometheus.yml` into your local
   Prometheus configuration and reload Prometheus.
4. In local Grafana, import `universalconverterx-grafana-dashboard.json` and
   select that Prometheus data source when prompted.

The dashboard shows live jobs, retained queryable jobs, cumulative starts, and
success/failure rates by engine. Counters reset when `ucx serve` restarts.
Finished job details remain queryable for one hour; that retention affects only
the `ucx_jobs_retained` gauge, not cumulative counters.

Quick check:

```powershell
Invoke-WebRequest http://127.0.0.1:17654/metrics -Headers @{ Authorization = "Bearer <token>" } | Select-Object -Expand Content
```
