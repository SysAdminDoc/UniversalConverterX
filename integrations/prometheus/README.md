# Local Prometheus and Grafana

`ucx serve` exposes Prometheus text-format metrics at
`http://127.0.0.1:17654/metrics`. The listener is loopback-only; UCX does not
send metrics anywhere, run a telemetry agent, or require Prometheus/Grafana.

1. Start the local API: `ucx serve --port 17654`.
2. Copy the `scrape_configs` entry from `prometheus.yml` into your local
   Prometheus configuration and reload Prometheus.
3. In local Grafana, import `universalconverterx-grafana-dashboard.json` and
   select that Prometheus data source when prompted.

The dashboard shows live jobs, retained queryable jobs, cumulative starts, and
success/failure rates by engine. Counters reset when `ucx serve` restarts.
Finished job details remain queryable for one hour; that retention affects only
the `ucx_jobs_retained` gauge, not cumulative counters.

Quick check:

```powershell
Invoke-WebRequest http://127.0.0.1:17654/metrics | Select-Object -Expand Content
```
