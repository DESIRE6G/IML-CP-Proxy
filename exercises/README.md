# P4 Runtime Proxy 

The goal of the P4Runtime Proxy is to create a layer between the data and control plane levels.
Its primary purpose is to be able to rearrange executive units hidden to the control plane without having to modify the control plane.
Its second purpose is that even if the data plane is rearranged, the control plane does not have to upload the various data again.

The combination of these two goals gives us the opportunity to 
1) break down the network functionalities into small elements and instead of having to maintain a larger P4 individual program, we create smaller functions and corresponding controllers and combine them;
2) break down a complex p4 program to multiple switches.
Since the Proxy also stores the entries, when a rearrangement takes place, almost nothing is sensible from the control plane and the user side.

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

For fully detailed paraméters, you can find `ProxyConfig` Pydantic model in proxy.py that determines the structure of the configuration files or you can find multiple testcases in the repository.

### Preload

The proxy can help you to preload entries in the dataplane on startup. 
For that you can check the `preload` examples in testcases.

## Use as lib

The Proxy can be used as a lib as well. 
You can directly create a Pydantic modell and pass it to the `start_servers_by_proxy_config` function.

If you need more detailed control on the tool, you can initiate the `ProxyServer` classes directly, check the source code for more information.

## Testing enviroment

The repository contains an automatic tester that run all the examples that can be generated. 
The testcase folder contains the main files for a test, but in the subtests we can create new folders that contains another files that can extend or overwrite the files the originates from the test folder.

After the test folder is built up in the `__temporary_test_folder` the redis is purged and if a `redis.json` is existing then uploads the content of that file.

When the redis and the files are in place the system creates a tmux and runs a mininet in it.
When it is ready it launches a proxy and a controller.py.

The basic testing is just start a ping from h1 to h2 node and check if it is going through.

If you add a `validator.py` into the folder in that case it will run after everything is running. 
That file can contain a code that connects to the proxy and requests information as a slave client and validate the end status of the test.
If that code exits with non-zero then the testcase fails.

If the testcase is failed the built testcase is reamins in the `__temporary_test_folder` folder that contains logs about the outputs of the tmux panes as well.

### Examples

Run all the test cases:

```python tester.py```

Run the l2fwd testcase without subtest:

```python tester.py l2fwd```

Run the l2fwd testcase simple_forward subtest:

```python tester.py l2fwd/simple_forward```

You can use asterix as wildcard for testcase and subtest as well:

```python tester.py */preload```

```python tester.py counter/*```

Build the `__temporary_test_folder` for the l2fwd testcase simple_forward subtest:

```python tester.py l2fwd/simple_forward```

Do a release into the `release` folder that contains all the necessary files to run the proxy without symlinks:

```python release```

Reload redis information for the actually built test folder:

```python prepare```

## Test config

If you add a `test_config.json` to the test case, you can configure the followings:

| Paramter name         | functionality                                                         | Defatult value      |
|-----------------------|-----------------------------------------------------------------------|---------------------|
| run_validator         | Determines if the tester run validator.py after the test case.        | true                |
| load_redis_json       | Determines if the tester fills up the redis from the redis.json file. | true                |
| start_controller      | Determines if the tester starts the controller.                       | true                |
| exact_ping_packet_num | Determines how many ping the tester will send to the h2 node.         | Run until a timeout |
| file_overrides        | You can give a dict that determines files to use.                     |                     |

To decrease redundancy there are `testcase_common` folder, that files are all copied to the test folder and with the `file_overrides` paramter we can use for example the defined topology there if we add the following config to our `test_config.json`.

```json
{
  "file_overrides": {
    "topology.json": "topology_h1_s1_h2.json"
  }
}
```

If you want to only extend or override some fields of the `test_config.json` placed into the test case folder, you can create a `test_case_extend.json`, that does not override fully the base config.
This feature is for further redundancy decrease.