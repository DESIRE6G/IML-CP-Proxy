# IML-CP-Proxy Mininet testing enviroment Guide

## Test enviroment in mininet virtual enviroment

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

### Test config

If you add a `test_config.json` to the test case, you can configure the followings:

| Field                 | Description                                                                                                                                                                       | Defatult value      |
|-----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------|
| start_mininet         | If it is true then the tester starts mininet for testing.                                                                                                                         | true                |
| start_proxy           | Determins if the tester starts the proxy.                                                                                                                                         | true                |
| start_controller      | Determines if the tester starts the controller.                                                                                                                                   | true                |
| run_validator         | Determines if the tester run validator.py after the test case.                                                                                                                    | true                |
| load_redis_json       | Determines if the tester fills up the redis from the redis.json file if it exists in the testcase folder. It helps to create test that assumes a start state of the redis.        | true                |
| file_overrides        | You can give a dict that determines files to use. More in [Test config subtest override](#test-config-subtest-override).                                                          |                     |
| ongoing_controller    | If it is set to false then the tester waits the controller to stop. If set the controller have to touch .controller_ready flag file to signal it is ready and the test can start. | false               |
| exact_ping_packet_num | Determines how many ping the tester will send to the h2 node.                                                                                                                     | Run until a timeout |

The actual PyDantic model can be found at [common/model/tester_config.py](common/model/tester_config.py)

#### Test config subtest override

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
