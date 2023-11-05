#include <core.p4>
#include <v1model.p4>

typedef bit<9>  egressSpec_t;
typedef bit<48> macAddr_t;

header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}

header states_t {
    bit<8>    state1;
    bit<8>    state2;
    bit<8>    state3;
}

struct metadata {
    egressSpec_t port; 
}

struct headers {
    ethernet_t   ethernet;
    states_t     states;
}

parser MyParser(packet_in packet,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {

    state start {
        packet.extract(hdr.ethernet);
        packet.extract(hdr.states);
        transition accept;
    }


}

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {   
    apply {  }
}

control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {
    counter(1, CounterType.packets_and_bytes) packetCounter3;

    action state_set(bit<8> newState) {
        hdr.states.state3 = newState;
    }

    table state_setter {
        key = {
            hdr.ethernet.dstAddr: exact;
        }
        actions = {
            state_set;
            NoAction;
        }
        size = 1024;
    }


    apply {
        state_setter.apply();
        packetCounter3.count((bit<32>) 0);
        packetCounter3.count((bit<32>) 0);
        packetCounter3.count((bit<32>) 0);
        standard_metadata.egress_spec = 2;
    }
}

control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply {  }
}

control MyComputeChecksum(inout headers  hdr, inout metadata meta) {
     apply { }
}

control MyDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.states);
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
