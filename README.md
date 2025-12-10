# IML-CP-Proxy
### P4Runtime-based Control Plane Proxy

[![Status](https://img.shields.io/badge/Status-Beta-blue)]()
[![CI](https://github.com/DESIRE6G/IML-CP-Proxy/actions/workflows/ci.yml/badge.svg)](https://github.com/DESIRE6G/IML-CP-Proxy/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

**IML-CP-Proxy** is a lightweight middleware that sits between a P4 Controller and your data plane. 
It allows you to **aggregate and disaggregate** P4 programs, merging multiple physical pipelines into a single virtual device (or vice versa). 
This simplifies control plane logic for complex, multi-switch or multi network function topologies.

## Quick Start (Demo)

See the proxy in action immediately with our self-contained demo. This launches the Proxy, a simulated Switch, and a dummy Controller.

```bash
git clone https://github.com/DESIRE6G/IML-CP-Proxy.git
cd IML-CP-Proxy
./run_demo.sh
```

- The script starts the full stack (Proxy, Redis, Switch, Controller).
- It automatically backs up any existing proxy_config.json you have.


## Static usage

To use IML-CP-Proxy with your own hardware and controller:

1) Configure: Copy the example config and edit it to match your physical switches.
```bash
cp example/proxy_config.json proxy_config.json
nano proxy_config.json
```
2) Customize: Change your proxy_config by your needs. Check the [configuration guide](docs/configuration.md) for details.
3) Run: Start only the Proxy and Redis (without the demo components). 
```bash
docker-compose up -d
```

3) Connect
- Point your P4 Controller to the correct port configured in proxy_config.json (e.g.: localhost:60051)
- The Proxy will route and transform requests to the switches defined in your config.

## Dynamic usage 

The Proxy can be used as a lib as well if you want to modify the config of the proxy in runtime. 
To learn more open the [IML-CP-Proxy as a Python Library Guide](docs/lib_use.md).

## Architecture

The proxy acts as a translation layer. It presents a "Virtual Device" to the controller(s), while managing the complexity of routing flow entries to the correct physical switches (S1, S2, etc.) in the background.

```mermaid
graph TD
    %% Define the style for the nodes
    classDef controller fill:#d4edda,stroke:#28a745,stroke-width:2px,color:#155724;
    classDef proxy fill:#cce5ff,stroke:#004085,stroke-width:2px,color:#004085;
    classDef database fill:#fff3cd,stroke:#856404,stroke-width:2px,color:#856404,stroke-dasharray: 5 5;
    classDef switch fill:#f8d7da,stroke:#721c24,stroke-width:2px,color:#721c24;

    %% Controller Node
    C["P4 Controller<br/>(e.g., ONOS, Python script)"]:::controller

    %% Main Proxy Subgraph
    subgraph Proxy_Layer [IML-CP-Proxy Layer]
        direction TB
        P["Proxy Core<br/>(Translation & Logic)<br/><b>Aggregates S1 & S2 into one Virtual Device</b>"]:::proxy
        R[("Redis DB<br/>State Storage")]:::database
        P <-->|Reads/Writes| R
    end

    %% Switch Nodes
    subgraph Data_Plane [Data Plane P4 Switches]
        S1["Switch 1<br/>(Function A)"]:::switch
        S2["Switch 2<br/>(Function B)"]:::switch
    end

    %% Connections
    C -->|"P4Runtime (Virtual View)"| P
    P -->|"P4Runtime (Physical View)"| S1
    P -->|"P4Runtime (Physical View)"| S2

    %% Link style
    linkStyle 0,2,3 stroke:#333,stroke-width:2px,fill:none;
    linkStyle 1 stroke:#856404,stroke-width:2px,fill:none,stroke-dasharray: 5 5;
```

**Key Features**
- Virtualization: Merges distinct P4 pipelines (e.g., L2FWD + Firewall) into one logical view.
- Transparent Proxy: Uses standard P4Runtime gRPC; no changes needed on the Controller side.
- State Management: Uses Redis to track flow rule mappings and device states.

## Manual installation

The system tested on Ubuntu 24.04.2 LTS with python3.8.10, so we suggest to use uv to install the desired python version and the dependencies.

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

cd IML-CP-Proxy/

# Create a virtualenv
uv venv --python 3.8.10
source .venv/bin/activate

# Install requirements
uv pip install -r requirements.txt
```

After the requirements installed, head to the [configuration guide](docs/configuration.md) and create the `proxy_config.json` to configure the proxy.

##  Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss what you would like to change.
To use the test system read the [IML-CP-Proxy Mininet testing enviroment Guide](docs/testing.md).

## License

Distributed under the Apache 2.0 License. See [LICENSE](LICENSE) for more information.
