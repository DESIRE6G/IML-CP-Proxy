/* -*- P4_16 -*- */
#include <core.p4>
#include <v1model.p4>

typedef bit<48> macAddr_t;

header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}

struct metadata {
    bit<32> NF1_meter_tag;
}

struct headers {
    ethernet_t   ethernet;
}

parser MyParser(packet_in packet,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {

    state start {
        packet.extract(hdr.ethernet);
        transition accept;
    }
}

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply {  }
}


control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {

    direct_meter<bit<32>>(MeterType.packets) NF1_my_meter;

    action NF1_drop() {
        mark_to_drop(standard_metadata);
    }

    action NF1_m_action() {
        NF1_my_meter.read(meta.NF1_meter_tag);
    }


    table NF1_m_read {
        key = {
            hdr.ethernet.srcAddr: exact;
        }
        actions = {
            NF1_m_action;
            NoAction;
        }
        default_action = NoAction;
        meters = NF1_my_meter;
        size = 16384;
    }

    table NF1_m_filter {
        key = {
            meta.NF1_meter_tag: exact;
        }
        actions = {
            NF1_drop;
            NoAction;
        }
        default_action = NF1_drop;
        size = 16;
    }

    apply {
        standard_metadata.egress_spec = 2;
        NF1_m_read.apply();
        NF1_m_filter.apply();
    }
}


control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply {}
}

control MyComputeChecksum(inout headers hdr, inout metadata meta) {
     apply {}
}

control MyDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
    }
}

V1Switch(
MyParser(),
MyVerifyChecksum(),
MyIngress(),
MyEgress(),
MyComputeChecksum(),
MyDeparser()
) main;