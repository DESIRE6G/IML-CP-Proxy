# P4 Runtime Proxy

The purpose of the P4Runtime Proxy is to create a layer between the data and control plane levels.
Its primary purpose is to be able to rearrange executive units hidden to the control plane without having to modify the control plane.
Its second purpose is that even if the data plane is rearranged, the control plane does not have to upload the various data again.

The combination of these two goals gives us the opportunity to 
1) break down the network functionalities into small elements and instead of having to maintain a larger P4 individual program, we create smaller functions and corresponding controllers and combine them;
2) break down a complex p4 program to multiple switches.
Since the Proxy also stores the entries, when a rearrangement takes place, almost nothing is sensible from the control plane and the user side.


## Install notes

To install you need to install Python3 and the following commands to install dependencies.

```
pip3 install --upgrade pip
python3 -m pip install --upgrade setuptools
sudo apt-get install python3-dev
pip3 install --no-cache-dir  --force-reinstall -Iv grpcio==1.65.5
pip3 install -r requirements.txt
```

## JSON Usage

The proxy can be configured via a JSON file.
In this file, you can specify mutiple mappings that configure the operation of the proxy.
A mapping contains targets and sources nodes to which we want to apply the proxy.
If we have multiple source and one target we will aggregate several basic functions into this node.
If we have multiple targets and one source then we will disaggregate the P4 program.
It also includes the corresponding P4 file and the connection data of the GRPC server.
The proxy will connect to it and appear as a controller for the data plane.
In addition to the target, we must specify the mapping sources and the corresponding p4 files, these sources are the functions which we want to combine.
In the case of sources, we also specify a prefix that has to be added to the beginning of the entity names in the merged P4 file, so we can avoid name conflicts in the case of the aggregated P4 file.

## Example

One of the most basic example configurations that combines 2 functions onto one target node is shown below. The table name ipv4_lpm in the function1.p4 file should appear as NF1_ipv4_lpm in the aggregated.p4 file.

```JSON
{
  "redis": "READWRITE",
  "mappings": [
    {
      "target": {
        "program_name": "aggregated",
        "port": 50051,
        "device_id": 0
      },
      "sources": [
        {
          "program_name": "function1",
          "prefix": "NF1_",
          "port": 60051
        },
        {
          "program_name": "function2",
          "prefix": "NF2_",
          "port": 60052
        }
      ]
    }
  ]
}
```

In this case, when the proxy receives from the controller of the function1 program for the ipv4_lpm table a table entry insert, the proxy receives a unique key in the message that identifies the table. This identifier is resolved by the proxy based on the p4info file generated from the function1.p4 file (function1.p4info file). It resolves to MyIngress.ipv4_lpm. This full name will be prefixed by the proxy, as a result of which we will get the name MyIngress.NF1_ipv4_lpm, which will finally be converted into an identifier based on the aggregated.p4info file. We do the same conversion for the actions of the table insert entry and with the new identifiers obtained in this way, we generate the new message, which we can now send to the node running the aggregated P4 program.

In production the typical mode is used for Redis is `READWRITE`, but for testing purpose there are different modes:

| Key        | Effect                                                              |
|------------|---------------------------------------------------------------------|
| READWRITE  | Reads entries from redis and write updates it on change             |
| ONLY_WRITE | Does not read on startup, but update                                |
| ONLY_READ  | Only load entries from redis on startup, but do not save any change |
| OFF        | Do not use redis entirely                                           |

The configuration can accept `source` for one source, `sources` for mutliple sources. `target` and `targets` similarly handled.

For fully detailed paraméters, you can find `ProxyConfig` Pydantic model in proxy_config.py that determines the structure of the configuration files.

### Preload

The proxy can help you to preload entries in the dataplane on startup, like you can see in the following example. The types can be: table, meter, direct_meter, counter, direct_counter.

```
{
  "redis": "OFF",
  "mappings": [
    {
      "targets": [
        {
          "program_name": "basicv4_part_1",
          "port": 50051,
          "device_id": 0,
          "names": {
            "MyIngress.ipv4_lpm1": "MyIngress.ipv4_lpm1"
          }
        },
        {
          "program_name": "basicv4_part_2",
          "port": 50052,
          "device_id": 1,
          "names": {
            "MyIngress.ipv4_lpm2": "MyIngress.ipv4_lpm2"
          }
        },
        {
          "program_name": "basicv4_part_3",
          "port": 50053,
          "device_id": 2,
          "names": {
            "MyIngress.just_another": "MyIngress.just_another"
          }
        },
        {
          "program_name": "fwd2p3",
          "port": 50054,
          "device_id": 3
        }
      ],
      "source":
      {
        "program_name": "basicv4",
        "port": 60051
      },
      "preload_entries": [
        {
          "type": "table",
          "parameters": {
            "table_name":"MyIngress.selector_table",
            "match_fields":{
              "meta.selector": 1
            },
            "action_name":"MyIngress.set_out_port",
            "action_params": {
              "port": 2
            }
          }
        },
        {
          "type": "table",
          "parameters": {
            "table_name":"MyIngress.selector_table",
            "match_fields":{
              "meta.selector": 2
            },
            "action_name":"MyIngress.set_out_port",
            "action_params": {
              "port": 3
            }
          }
        }
      ]
    }
  ]
}
```

## Use as lib

The Proxy can be used as a lib as well.
You can directly create a Pydantic modell and pass it to the `start_servers_by_proxy_config` function.

If you need more detailed control on the tool, you can initiate the `ProxyServer` classes directly.