#!/usr/bin/env python3
import argparse
import asyncio

from p4.v1 import p4runtime_pb2

from common.controller_helper import get_now_ts_us_int32
from common.high_level_switch_connection_async import HighLevelSwitchConnection


async def sender_task(index: int, program_name: str, prefix: str, target_port: int, batch_size: int, rate_limit: int = None):
    print(f'sender_task started {index=} {program_name=} {prefix=} {target_port=} {batch_size=} {rate_limit=} part{index+1}')

    s = HighLevelSwitchConnection(
        device_id=index,
        filename=program_name,
        port=target_port,
        send_p4info=True,
        reset_dataplane=True,
        rate_limit=rate_limit
    )
    await s.init()

    while True:
        request = p4runtime_pb2.WriteRequest()
        request.device_id = 0
        request.election_id.low = 1
        ts = get_now_ts_us_int32()
        for _ in range(batch_size):
            table_entry = s.p4info_helper.build_table_entry(
                table_name=f"MyIngress.{prefix}state_setter",
                match_fields={
                    'hdr.ethernet.dstAddr': '08:00:00:00:02:22'
                },
                action_name=f"MyIngress.{prefix}state_set",
                action_params={
                    "newState": ts
                }
            )
            update = request.updates.add()
            update.type = p4runtime_pb2.Update.INSERT
            update.entity.table_entry.CopyFrom(table_entry)
        await s.connection.client_stub.Write(request)

        await asyncio.sleep(0)


async def main():
    parser = argparse.ArgumentParser(prog='Validator')
    parser.add_argument('--batch_size', default=1, type=int)
    parser.add_argument('--sender_num', default=1, type=int)
    parser.add_argument('--rate_limit', default=None, type=int)
    parser.add_argument('--target_port', default='60051')
    parser.add_argument('--dominant_sender_rate_limit', default=None, type=int)
    args = parser.parse_args()

    tasks = []
    for i in range(args.sender_num):
        if args.dominant_sender_rate_limit is not None and i == 0:
            rate_limit = args.dominant_sender_rate_limit
        else:
            rate_limit = args.rate_limit

        if int(args.target_port) < 60000:
            program_name = 'aggregated1234'
            prefix = f'part{i+1}_'
        else:
            program_name = f'part{i+1}'
            prefix = ''

        task = asyncio.create_task(
            sender_task(i, program_name, prefix, int(args.target_port) + i, args.batch_size, rate_limit)
        )
        tasks.append(task)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        print('Tasks cancelled, stopping.')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('KeyboardInterrupt arrived, stopping.')