# `nvidia-smi` Sender

_as seen in the famous article [Cloud GPUs Thermal Throttle to 25% Performance](https://matt.sh/cloud-gpu-thermal-throttling)_

Do you know how your GPUs are performing?

You *are* monitoring your GPU thermal headroom, right? You are aware if your performance is being limited by thermal throttling, right? _right????_

## What

`nvidia-smi-sender` is a client-side push agent for sending your GPU hardware performance statistics to a [Victoria Metrics](https://github.com/VictoriaMetrics/VictoriaMetrics) log collector you can then read using a standard [Grafana](https://github.com/grafana/grafana) setup (or whatever else you want to use).

The metrics collected by default are currently:

- `pstate`
- `power.management`
- `power.draw`
- `power.draw.average`
- `power.draw.instant`
- `power.limit`
- `power.default_limit`
- `power.min_limit`
- `power.max_limit`
- `temperature.gpu`
- `temperature.memory`
- `memory.used`
- `memory.total`
- `memory.free`
- `clocks.current.sm`
- `clocks.current.memory`
- `clocks_throttle_reasons.supported`
- `clocks_throttle_reasons.active`
- `clocks_throttle_reasons.gpu_idle`
- `clocks_throttle_reasons.applications_clocks_setting`
- `clocks_throttle_reasons.sw_power_cap`
- `clocks_throttle_reasons.hw_slowdown`
- `clocks_throttle_reasons.hw_thermal_slowdown`
- `clocks_throttle_reasons.hw_power_brake_slowdown`
- `clocks_throttle_reasons.sw_thermal_slowdown`
- `clocks_throttle_reasons.sync_boost`

The most useful metrics for tracking GPU throttling due to poor cooling issues are:

- `power.draw.average`
- `power.draw.instant`
- `power.max_limit`
- `temperature.gpu`
- `temperature.memory`
- `clocks.current.sm`
- `clocks.current.memory`
- `clocks_throttle_reasons.hw_thermal_slowdown`
- `clocks_throttle_reasons.sw_thermal_slowdown`

For example, this server is ass:

![thermally throttled CPU](https://mattsta.b-cdn.net/cloud-gpu-bad/clean-start-clock.png "hopefully your results aren't this bad")

## How

How does it work?

The nvidia-provided command line utility `nvidia-smi` includes an option for streaming CSV output, so we just open the CSV stream, read it, collect batches of metrics, then send batched historically timestamped metrics to the metrics server.

By default we collect high frequency metrics every 10 ms, but you can adjust the frequency longer or shorter as needed.

## Limitations

Currently we assume only one GPU exists. This is not always true. Free to submit improvements or provide access to free multi-GPU servers for more advancement development.

## Usage (agent)

To run the agent:

```bash
# fetch
pip install pip poetry -U
git clone https://github.com/mattsta/nvidia-smi-sender
cd nvidia-smi-sender

# install dependencies
poetry install

# run it (send metrics to victoria metics host; collect metrics every 10 milliseconds; send 1,000 collections)
poetry run nvidia-smi-sender --host=http://localhost:8428 --ms=10 --batch-size=1000 -- stream_gpu_info
```

Startup looks like:

```haskell
$ poetry run nvidia-smi-sender --host=http://localhost:8428 --batch-size=768 -- stream_gpu_info
nvidia_smi_sender.agent:cmd:254 - Sending remote metrics every 7.68 seconds (reading 10 ms; batching 768 metrics per-send)
nvidia_smi_sender.agent:cmd:254 - [http://localhost:8428/api/v1/import] Created agent for sending GPU stats...
```

## Usage (Backend)

For quick testing, you can set up a logs collector and graphing platform locally as easy as:

```bash
brew update
brew install victoriametrics
brew install grafana
```

Then in two console tabs just run the servers when you need them (these are the standard commands printed when you install using brew):

```bash
/opt/homebrew/opt/victoriametrics/bin/victoria-metrics \
    -httpListenAddr=127.0.0.1:8428 \
    -promscrape.config=/opt/homebrew/etc/victoriametrics/scrape.yml \
    -storageDataPath=/opt/homebrew/var/victoriametrics-data
```

```bash
/opt/homebrew/opt/grafana/bin/grafana server \
    --config /opt/homebrew/etc/grafana/grafana.ini \
    --homepath /opt/homebrew/opt/grafana/share/grafana \
    --packaging=brew \
    cfg:default.paths.logs=/opt/homebrew/var/log/grafana \
    cfg:default.paths.data=/opt/homebrew/var/lib/grafana \
    cfg:default.paths.plugins=/opt/homebrew/var/lib/grafana/plugins
```

This works as a temporary/testing setup where defaults everywhere is fine (like admin/admin to the grafana dashboard on localhost:3000), but for stronger production usage you would want to audit all the configuration settings, use a proper storage locations, etc.

Notice you are running the logs collector on `-httpListenAddr=127.0.0.1:8428`, so for remote testing, you can reverse port forward your local port into a remote machine, then the remote machine can log to its localhost for transparently sending results back to your localhost.

You can optionally skip using grafana and just load the victoria metrics built-in metrics+graph explorer at http://localhost:8428/vmui/ too.

### Reverse Port Forward Metrics Server to Remote Hosts

```bash
autossh -M0 -N -C -R 127.0.0.1:8428:127.0.0.1:8428 remoteuser@remotehost
```

Now the remote server has ssh listening on `-R 127.0.0.1:8428` which forward to your source host (what opened the ssh connection) to `:127.0.0.1:8428`.

(somewhat bad example since the target/source specs are the same (we _do_ want to use localhost for all these here though), but the pattern is REMOTE_HOST:REMOTE_PORT:LOCAL_HOST:LOCAL_PORT (and REMOTE_HOST is optional if you want it to bind to `*` so sometimes you lazily see things like `-R 80:localhost:80`), so the first `127.0.0.1:8428` is the remote host opening a port on _its_ localhost:8428, and the second `:127.0.0.1:8428` is your local host offering your forwarding-from machine binding to the remote reverse port opened by the ssh client)
