# IML-CP-Proxy as a Python Library Guide

The Proxy can be used as a lib as well.
If you initiate the `ProxyServer` class and configure as desired, then you can `add_target_switch` or `remove_from_filter_params_allow_only_to_host` in runtime. 
If you need more detailed control on the tool, you can initiate the `ProxyServer` classes directly, check the source code for more information.

A simple forward proxy can be set up as the following.
```python
import asyncio
from proxy import ProxyServer, ProxyConfigTarget, ProxyConfigSource


async def run_proxy():
    # 1. Define your Target (The Physical Switch)
    target_switch = ProxyConfigTarget(
        program_name="simple_switch",
        port=50051,
        device_id=1,
        host="127.0.0.1"
    )

    # 2. Define your Source (The Virtual Interface for Controller)
    controller_interface = ProxyConfigSource(
        program_name="simple_switch",
        port=60051,
        prefix="" # No prefix needed for simple forward proxy
    )

    # 3. Create the ProxyServer Instance Directly
    # We explicitly pass the source, target(s), and redis mode here.
    server = ProxyServer(
        name="MyManualProxy",
        source=controller_interface,
        target=target_switch,  # Use 'targets=[...]' for disaggregation
        redis_mode="OFF"       # or "READWRITE"
    )

    # 4. Start the Server
    # The .start() method is non-blocking (it creates background tasks)
    print(f"Starting Proxy on port {controller_interface.port}...")
    await server.start()

    # 5. Keep the Main Thread Alive
    # Since server.start() is backgrounded, we must prevent the script from exiting.
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        print("Stopping proxy...")

if __name__ == "__main__":
    asyncio.run(run_proxy())
```

## Injecting a switch connection to the proxy

You can initialize a `HighLevelSwitchConnectionAsync` manually and pass it into the `ProxyServer` instead of a configuration.
This bypasses the proxy's internal connection logic, allowing you to share the connection object and have more control on the target switch conections.

```python
import asyncio
from proxy import ProxyServer, ProxyConfigSource
from common.high_level_switch_connection_async import HighLevelSwitchConnectionAsync

async def run_proxy_with_injected_connection():
    # Setup the connection MANUALLY
    shared_connection = HighLevelSwitchConnectionAsync(
        name="SharedSwitchConn",
        address="127.0.0.1:50051",
        device_id=1,
        # Ensure these paths are correct relative to execution
        p4info_path="build/l2fwd.p4.p4info.txt",
        bmv2_json_path="build/l2fwd.json"
    )

    # Connect and Initialize (Handshake)
    await shared_connection.connect()

    server = ProxyServer(
        name="InjectedProxy",
        source=ProxyConfigSource(program_name="logical_device", port=60051),        
        target_switche_configs_or_one_connection=shared_connection,         
        redis_mode="OFF"
    )

    await server.start()
    print(f"Proxy is running on port 60051, using the pre-existing connection.")

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        print("Stopping...")

if __name__ == "__main__":
    asyncio.run(run_proxy_with_injected_connection())
```