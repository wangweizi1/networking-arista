# Copyright (c) 2013 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import functools
import operator
import socket

import mock
from mock import patch
from neutron_lib import constants as n_const
from neutron_lib.plugins import constants as plugin_constants
from neutron_lib.plugins import directory
from oslo_config import cfg
from oslo_utils import importutils

from neutron.tests.unit import testlib_api

from networking_arista.common import db_lib
from networking_arista.ml2.rpc import arista_json
import networking_arista.tests.unit.ml2.utils as utils


BASE_RPC = "networking_arista.ml2.rpc.arista_json.AristaRPCWrapperJSON."
JSON_SEND_FUNC = BASE_RPC + "_send_api_request"
RAND_FUNC = BASE_RPC + "_get_random_name"


def setup_valid_config():
    utils.setup_arista_wrapper_config(cfg)


class _UnorderedDictList(list):
    def __init__(self, iterable='', sort_key=None):
        super(_UnorderedDictList, self).__init__(iterable)
        try:
            (self[0] or {})[sort_key]
            self.sort_key = sort_key
        except (IndexError, KeyError):
            self.sort_key = None

    def __eq__(self, other):
        if isinstance(other, list) and self.sort_key:
            key = operator.itemgetter(self.sort_key)
            return sorted(self, key=key) == sorted(other, key=key)
        else:
            return super(_UnorderedDictList, self).__eq__(other)


class TestAristaJSONRPCWrapper(testlib_api.SqlTestCase):
    def setUp(self):
        super(TestAristaJSONRPCWrapper, self).setUp()
        plugin_klass = importutils.import_class(
            "neutron.db.db_base_plugin_v2.NeutronDbPluginV2")
        directory.add_plugin(plugin_constants.CORE, plugin_klass())
        setup_valid_config()
        ndb = db_lib.NeutronNets()
        self.drv = arista_json.AristaRPCWrapperJSON(ndb)
        self.drv._server_ip = "10.11.12.13"
        self.region = 'RegionOne'

    def _verify_send_api_request_call(self, mock_send_api_req, calls,
                                      unordered_dict_list=False):
        if unordered_dict_list:
            wrapper = functools.partial(_UnorderedDictList, sort_key='id')
        else:
            wrapper = lambda x: x

        expected_calls = [
            mock.call(c[0], c[1], *(wrapper(d) for d in c[2:])) for c in calls
        ]

        mock_send_api_req.assert_has_calls(expected_calls, any_order=True)

    @patch(JSON_SEND_FUNC)
    def test_register_with_eos(self, mock_send_api_req):
        self.drv.register_with_eos()
        calls = [
            ('region/RegionOne', 'PUT',
             [{'name': 'RegionOne', 'syncInterval': 10}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    def _get_random_name(self):
        return 'thisWillBeRandomInProd'

    @patch(JSON_SEND_FUNC)
    @patch(RAND_FUNC, _get_random_name)
    def test_sync_start(self, mock_send_api_req):
        mock_send_api_req.side_effect = [
            [{'name': 'RegionOne', 'syncStatus': ''}],
            [{}],
            [{'syncStatus': 'syncInProgress',
              'requestId': self._get_random_name()}]
        ]
        assert self.drv.sync_start()
        calls = [
            ('region/RegionOne/sync', 'POST',
             {'requester': socket.gethostname().split('.')[0],
              'requestId': self._get_random_name()})
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    @patch(RAND_FUNC, _get_random_name)
    def test_sync_end(self, mock_send_api_req):
        mock_send_api_req.return_value = [{'requester':
                                           self._get_random_name()}]
        self.drv.current_sync_name = self._get_random_name()
        assert self.drv.sync_end()
        calls = [
            ('region/RegionOne/sync', 'DELETE')
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    def test_create_region(self, mock_send_api_req):
        self.drv.create_region('foo')
        calls = [('region/', 'POST', [{'name': 'foo'}])]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    def test_delete_region(self, mock_send_api_req):
        self.drv.delete_region('foo')
        calls = [('region/', 'DELETE', [{'name': 'foo'}])]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    def test_get_tenants(self, mock_send_api_req):
        self.drv.get_tenants()
        calls = [('region/RegionOne/tenant', 'GET')]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    def test_delete_tenant_bulk(self, mock_send_api_req):
        self.drv.delete_tenant_bulk(['t1', 't2'])
        calls = [('region/RegionOne/tenant', 'DELETE',
                  [{'id': 't1'}, {'id': 't2'}])]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    def _createNetworkData(self, tenant_id, network_id, shared=False,
                           seg_id=100, network_type='vlan'):
        return {
            'network_id': network_id,
            'tenantId': tenant_id,
            'shared': shared,
            'segments': [{'segmentation_id': seg_id,
                          'physical_network': 'default',
                          'id': 'segment_id_1',
                          'is_dynamic': False,
                          'network_type': network_type}],
        }

    @patch(JSON_SEND_FUNC)
    def test_create_network_bulk(self, mock_send_api_req):
        n = []
        n.append(self._createNetworkData('t1', 'net1', seg_id=100))
        n.append(self._createNetworkData('t1', 'net2', seg_id=200))
        n.append(self._createNetworkData('t1', 'net3', network_type='flat'))
        self.drv.create_network_bulk('t1', n)
        calls = [
            ('region/RegionOne/network', 'POST',
             [{'id': 'net1', 'tenantId': 't1', 'shared': False},
              {'id': 'net2', 'tenantId': 't1', 'shared': False},
              {'id': 'net3', 'tenantId': 't1', 'shared': False}]),
            ('region/RegionOne/segment', 'POST',
                [{'id': 'segment_id_1', 'networkId': 'net1', 'type': 'vlan',
                  'segmentationId': 100, 'segmentType': 'static'},
                 {'id': 'segment_id_1', 'networkId': 'net2', 'type': 'vlan',
                  'segmentationId': 200, 'segmentType': 'static'}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls, True)

    @patch(JSON_SEND_FUNC)
    def test_delete_network_bulk(self, mock_send_api_req):
        self.drv.delete_network_bulk('t1', ['net1', 'net2'])
        calls = [
            ('region/RegionOne/network', 'DELETE',
             [{'id': 'net1', 'tenantId': 't1'},
              {'id': 'net2', 'tenantId': 't1'}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls, True)

    @patch(JSON_SEND_FUNC)
    def test_create_network_segments(self, mock_send_api_req):
        segments = [{'segmentation_id': 101,
                     'physical_network': 'default',
                     'id': 'segment_id_1',
                     'is_dynamic': False,
                     'network_type': 'vlan'},
                    {'segmentation_id': 102,
                     'physical_network': 'default',
                     'id': 'segment_id_2',
                     'is_dynamic': True,
                     'network_type': 'vlan'}]
        self.drv.create_network_segments('t1', 'n1', 'net1', segments)
        calls = [
            ('region/RegionOne/segment', 'POST',
                [{'id': 'segment_id_1', 'networkId': 'n1', 'type': 'vlan',
                  'segmentationId': 101, 'segmentType': 'static'},
                 {'id': 'segment_id_2', 'networkId': 'n1', 'type': 'vlan',
                  'segmentationId': 102, 'segmentType': 'dynamic'}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls, True)

    @patch(JSON_SEND_FUNC)
    def test_delete_network_segments(self, mock_send_api_req):
        segments = [{'segmentation_id': 101,
                     'physical_network': 'default',
                     'id': 'segment_id_1',
                     'is_dynamic': False,
                     'network_type': 'vlan'},
                    {'segmentation_id': 102,
                     'physical_network': 'default',
                     'id': 'segment_id_2',
                     'is_dynamic': True,
                     'network_type': 'vlan'}]
        self.drv.delete_network_segments('t1', segments)
        calls = [
            ('region/RegionOne/segment', 'DELETE',
                [{'id': 'segment_id_1'},
                 {'id': 'segment_id_2'}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    def test_create_instance_bulk(self, mock_send_api_req):
        tenant_id = 'ten-3'
        num_devices = 8
        num_ports_per_device = 2

        device_count = 0
        devices = {}
        for device_id in range(0, num_devices):
            dev_id = 'dev-id-%d' % device_id
            devices[dev_id] = {'vmId': dev_id,
                               'baremetal_instance': False,
                               'ports': []
                               }
            for port_id in range(0, num_ports_per_device):
                port_id = 'port-id-%d-%d' % (device_id, port_id)
                port = {
                    'device_id': 'dev-id-%d' % device_id,
                    'hosts': ['host_%d' % (device_count)],
                    'portId': port_id
                }
                devices[dev_id]['ports'].append(port)
            device_count += 1

        device_owners = [n_const.DEVICE_OWNER_DHCP,
                         'compute',
                         'baremetal',
                         n_const.DEVICE_OWNER_DVR_INTERFACE]
        port_list = []

        net_count = 0
        for device_id in range(0, num_devices):
            for port_id in range(0, num_ports_per_device):
                port = {
                    'portId': 'port-id-%d-%d' % (device_id, port_id),
                    'device_id': 'dev-id-%d' % device_id,
                    'device_owner': device_owners[device_id % 4],
                    'network_id': 'network-id-%d' % net_count,
                    'name': 'port-%d-%d' % (device_id, port_id),
                    'tenant_id': tenant_id,
                }
                port_list.append(port)
                net_count += 1

        create_ports = {}
        for port in port_list:
            create_ports.update(utils.port_dict_representation(port))

        profiles = {}
        for port in port_list:
            profiles[port['portId']] = {'vnic_type': 'normal'}
            if port['device_owner'] == 'baremetal':
                profiles[port['portId']] = {
                    'vnic_type': 'baremetal',
                    'profile': '{"local_link_information":'
                    '[{"switch_id": "switch01", "port_id": "Ethernet1"}]}'}
        self.drv.create_instance_bulk(tenant_id, create_ports, devices,
                                      profiles)
        calls = [
            ('region/RegionOne/tenant?tenantId=ten-3', 'GET'),
            ('region/RegionOne/dhcp?tenantId=ten-3', 'POST',
                [{'id': 'dev-id-0', 'hostId': 'host_0'},
                 {'id': 'dev-id-4', 'hostId': 'host_4'}]),
            ('region/RegionOne/vm?tenantId=ten-3', 'POST',
                [{'id': 'dev-id-1', 'hostId': 'host_1'},
                 {'id': 'dev-id-5', 'hostId': 'host_5'}]),
            ('region/RegionOne/baremetal?tenantId=ten-3', 'POST',
                [{'id': 'dev-id-2', 'hostId': 'host_2'},
                 {'id': 'dev-id-6', 'hostId': 'host_6'}]),
            ('region/RegionOne/router?tenantId=ten-3', 'POST',
                [{'id': 'dev-id-3', 'hostId': 'host_3'},
                 {'id': 'dev-id-7', 'hostId': 'host_7'}]),
            ('region/RegionOne/port', 'POST',
                [{'networkId': 'network-id-0', 'id': 'port-id-0-0',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-0',
                  'name': 'port-0-0', 'hosts': ['host_0'],
                  'instanceType': 'dhcp', 'vlanType': 'allowed'},
                 {'networkId': 'network-id-1', 'id': 'port-id-0-1',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-0',
                  'name': 'port-0-1', 'hosts': ['host_0'],
                  'instanceType': 'dhcp', 'vlanType': 'allowed'},

                 {'networkId': 'network-id-2', 'id': 'port-id-1-0',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-1',
                  'name': 'port-1-0', 'hosts': ['host_1'],
                  'instanceType': 'vm', 'vlanType': 'allowed'},
                 {'networkId': 'network-id-3', 'id': 'port-id-1-1',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-1',
                  'name': 'port-1-1', 'hosts': ['host_1'],
                  'instanceType': 'vm', 'vlanType': 'allowed'},

                 {'networkId': 'network-id-4', 'id': 'port-id-2-0',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-2',
                  'name': 'port-2-0', 'hosts': ['host_2'],
                  'instanceType': 'baremetal', 'vlanType': 'native'},
                 {'networkId': 'network-id-5', 'id': 'port-id-2-1',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-2',
                  'name': 'port-2-1', 'hosts': ['host_2'],
                  'instanceType': 'baremetal', 'vlanType': 'native'},

                 {'networkId': 'network-id-6', 'id': 'port-id-3-0',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-3',
                  'name': 'port-3-0', 'hosts': ['host_3'],
                  'instanceType': 'router', 'vlanType': 'allowed'},
                 {'networkId': 'network-id-7', 'id': 'port-id-3-1',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-3',
                  'name': 'port-3-1', 'hosts': ['host_3'],
                  'instanceType': 'router', 'vlanType': 'allowed'},

                 {'networkId': 'network-id-8', 'id': 'port-id-4-0',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-4',
                  'name': 'port-4-0', 'hosts': ['host_4'],
                  'instanceType': 'dhcp', 'vlanType': 'allowed'},
                 {'networkId': 'network-id-9', 'id': 'port-id-4-1',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-4',
                  'name': 'port-4-1', 'hosts': ['host_4'],
                  'instanceType': 'dhcp', 'vlanType': 'allowed'},

                 {'networkId': 'network-id-10', 'id': 'port-id-5-0',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-5',
                  'name': 'port-5-0', 'hosts': ['host_5'],
                  'instanceType': 'vm', 'vlanType': 'allowed'},
                 {'networkId': 'network-id-11', 'id': 'port-id-5-1',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-5',
                  'name': 'port-5-1', 'hosts': ['host_5'],
                  'instanceType': 'vm', 'vlanType': 'allowed'},

                 {'networkId': 'network-id-12', 'id': 'port-id-6-0',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-6',
                  'name': 'port-6-0', 'hosts': ['host_6'],
                  'instanceType': 'baremetal', 'vlanType': 'native'},
                 {'networkId': 'network-id-13', 'id': 'port-id-6-1',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-6',
                  'name': 'port-6-1', 'hosts': ['host_6'],
                  'instanceType': 'baremetal', 'vlanType': 'native'},

                 {'networkId': 'network-id-14', 'id': 'port-id-7-0',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-7',
                  'name': 'port-7-0', 'hosts': ['host_7'],
                  'instanceType': 'router', 'vlanType': 'allowed'},
                 {'networkId': 'network-id-15', 'id': 'port-id-7-1',
                  'tenantId': 'ten-3', 'instanceId': 'dev-id-7',
                  'name': 'port-7-1', 'hosts': ['host_7'],
                  'instanceType': 'router', 'vlanType': 'allowed'}]),

            ('region/RegionOne/port/port-id-0-0/binding',
             'POST', [{'portId': 'port-id-0-0', 'hostBinding': [
                      {'segment': [], 'host': 'host_0'}]}]),
            ('region/RegionOne/port/port-id-0-1/binding',
             'POST', [{'portId': 'port-id-0-1', 'hostBinding': [
                      {'segment': [], 'host': 'host_0'}]}]),

            ('region/RegionOne/port/port-id-1-0/binding',
             'POST', [{'portId': 'port-id-1-0', 'hostBinding': [
                      {'segment': [], 'host': 'host_1'}]}]),
            ('region/RegionOne/port/port-id-1-1/binding',
             'POST', [{'portId': 'port-id-1-1', 'hostBinding': [
                      {'segment': [], 'host': 'host_1'}]}]),

            ('region/RegionOne/port/port-id-2-0/binding',
             'POST', [{'portId': 'port-id-2-0', 'switchBinding': [
                      {'interface': u'Ethernet1', 'host': 'host_2',
                       'segment': [], 'switch': u'switch01'}]}]),
            ('region/RegionOne/port/port-id-2-1/binding',
             'POST', [{'portId': 'port-id-2-1', 'switchBinding': [
                      {'interface': u'Ethernet1', 'host': 'host_2',
                       'segment': [], 'switch': u'switch01'}]}]),

            ('region/RegionOne/port/port-id-3-0/binding',
             'POST', [{'portId': 'port-id-3-0', 'hostBinding': [
                      {'segment': [], 'host': 'host_3'}]}]),
            ('region/RegionOne/port/port-id-3-1/binding',
             'POST', [{'portId': 'port-id-3-1', 'hostBinding': [
                      {'segment': [], 'host': 'host_3'}]}]),

            ('region/RegionOne/port/port-id-4-0/binding',
             'POST', [{'portId': 'port-id-4-0', 'hostBinding': [
                      {'segment': [], 'host': 'host_4'}]}]),
            ('region/RegionOne/port/port-id-4-1/binding',
             'POST', [{'portId': 'port-id-4-1', 'hostBinding': [
                      {'segment': [], 'host': 'host_4'}]}]),

            ('region/RegionOne/port/port-id-5-0/binding',
             'POST', [{'portId': 'port-id-5-0', 'hostBinding': [
                      {'segment': [], 'host': 'host_5'}]}]),
            ('region/RegionOne/port/port-id-5-1/binding',
             'POST', [{'portId': 'port-id-5-1', 'hostBinding': [
                      {'segment': [], 'host': 'host_5'}]}]),

            ('region/RegionOne/port/port-id-6-0/binding',
             'POST', [{'portId': 'port-id-6-0', 'switchBinding': [
                      {'interface': u'Ethernet1', 'host': 'host_6',
                       'segment': [], 'switch': u'switch01'}]}]),
            ('region/RegionOne/port/port-id-6-1/binding',
             'POST', [{'portId': 'port-id-6-1', 'switchBinding': [
                      {'interface': u'Ethernet1', 'host': 'host_6',
                       'segment': [], 'switch': u'switch01'}]}]),

            ('region/RegionOne/port/port-id-7-0/binding',
             'POST', [{'portId': 'port-id-7-0', 'hostBinding': [
                      {'segment': [], 'host': 'host_7'}]}]),
            ('region/RegionOne/port/port-id-7-1/binding',
             'POST', [{'portId': 'port-id-7-1', 'hostBinding': [
                      {'segment': [], 'host': 'host_7'}]}]),
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls, True)

    @patch(JSON_SEND_FUNC)
    def test_delete_vm_bulk(self, mock_send_api_req):
        self.drv.delete_vm_bulk('t1', ['vm1', 'vm2'])
        calls = [
            ('region/RegionOne/vm', 'DELETE',
             [{'id': 'vm1'}, {'id': 'vm2'}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    def test_delete_dhcp_bulk(self, mock_send_api_req):
        self.drv.delete_dhcp_bulk('t1', ['dhcp1', 'dhcp2'])
        calls = [
            ('region/RegionOne/dhcp', 'DELETE',
             [{'id': 'dhcp1'}, {'id': 'dhcp2'}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    def test_delete_port(self, mock_send_api_req):
        self.drv.delete_port('p1', 'inst1', 'vm')
        self.drv.delete_port('p2', 'inst2', 'dhcp')
        calls = [
            ('region/RegionOne/port?portId=p1&id=inst1&type=vm',
             'DELETE',
             [{'hosts': [], 'id': 'p1', 'tenantId': None, 'networkId': None,
               'instanceId': 'inst1', 'name': None, 'instanceType': 'vm',
               'vlanType': 'allowed'}]),
            ('region/RegionOne/port?portId=p2&id=inst2&type=dhcp',
             'DELETE',
             [{'hosts': [], 'id': 'p2', 'tenantId': None, 'networkId': None,
               'instanceId': 'inst2', 'name': None, 'instanceType': 'dhcp',
               'vlanType': 'allowed'}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    def test_get_port(self, mock_send_api_req):
        self.drv.get_instance_ports('inst1', 'vm')
        calls = [
            ('region/RegionOne/port?id=inst1&type=vm',
             'GET')
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    def test_plug_virtual_port_into_network(self, mock_send_api_req):
        segments = [{'segmentation_id': 101,
                     'id': 'segment_id_1',
                     'network_type': 'vlan',
                     'is_dynamic': False}]
        self.drv.plug_port_into_network('vm1', 'h1', 'p1', 'n1', 't1', 'port1',
                                        'compute', None, None, None, segments)
        calls = [
            ('region/RegionOne/vm?tenantId=t1', 'POST',
             [{'id': 'vm1', 'hostId': 'h1'}]),
            ('region/RegionOne/port', 'POST',
             [{'id': 'p1', 'hosts': ['h1'], 'tenantId': 't1',
               'networkId': 'n1', 'instanceId': 'vm1', 'name': 'port1',
               'instanceType': 'vm', 'vlanType': 'allowed'}]),
            ('region/RegionOne/port/p1/binding', 'POST',
             [{'portId': 'p1', 'hostBinding': [{'host': 'h1', 'segment': [{
               'id': 'segment_id_1', 'type': 'vlan', 'segmentationId': 101,
               'networkId': 'n1', 'segment_type': 'static'}]}]}]),
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    @patch('networking_arista.ml2.rpc.arista_json.AristaRPCWrapperJSON.'
           'get_instance_ports')
    def test_unplug_virtual_port_from_network(self, mock_get_instance_ports,
                                              mock_send_api_req):
        mock_get_instance_ports.return_value = []
        self.drv.unplug_port_from_network('vm1', 'compute', 'h1', 'p1', 'n1',
                                          't1', None, None)
        port = self.drv._create_port_data('p1', None, None, 'vm1', None, 'vm',
                                          None)
        calls = [
            ('region/RegionOne/port/p1/binding', 'DELETE',
             [{'portId': 'p1', 'hostBinding': [{'host': 'h1'}]}]),
            ('region/RegionOne/port?portId=p1&id=vm1&type=vm',
             'DELETE', [port]),
            ('region/RegionOne/vm', 'DELETE', [{'id': 'vm1'}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    def test_plug_baremetal_port_into_network(self, mock_send_api_req):
        segments = [{'segmentation_id': 101,
                     'id': 'segment_id_1',
                     'network_type': 'vlan',
                     'is_dynamic': False}]
        sg = {'id': 'security-group-1'}
        switch_bindings = [{'switch_id': 'switch01', 'port_id': 'Ethernet1',
                            'switch_info': 'switch01'}]
        self.drv.plug_port_into_network('bm1', 'h1', 'p1', 'n1', 't1', 'port1',
                                        'baremetal', sg, None, 'baremetal',
                                        segments,
                                        switch_bindings=switch_bindings)
        calls = [
            ('region/RegionOne/baremetal?tenantId=t1', 'POST',
             [{'id': 'bm1', 'hostId': 'h1'}]),
            ('region/RegionOne/port', 'POST',
             [{'id': 'p1', 'hosts': ['h1'], 'tenantId': 't1',
               'networkId': 'n1', 'instanceId': 'bm1', 'name': 'port1',
               'instanceType': 'baremetal', 'vlanType': 'native'}]),
            ('region/RegionOne/port/p1/binding', 'POST',
             [{'portId': 'p1', 'switchBinding': [{'host': 'h1',
               'switch': 'switch01', 'interface': 'Ethernet1', 'segment': [{
                   'id': 'segment_id_1', 'type': 'vlan', 'segmentationId': 101,
                   'networkId': 'n1', 'segment_type': 'static'}]}]}]),
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    @patch('networking_arista.ml2.rpc.arista_json.AristaRPCWrapperJSON.'
           'get_instance_ports')
    def test_unplug_baremetal_port_from_network(self, mock_get_instance_ports,
                                                mock_send_api_req):
        mock_get_instance_ports.return_value = []
        switch_bindings = [{'switch_id': 'switch01', 'port_id': 'Ethernet1'}]
        self.drv.unplug_port_from_network('bm1', 'baremetal', 'h1', 'p1', 'n1',
                                          't1', None, 'baremetal',
                                          switch_bindings)
        port = self.drv._create_port_data('p1', None, None, 'bm1', None,
                                          'baremetal', None)
        calls = [
            ('region/RegionOne/port/p1/binding', 'DELETE',
             [{'portId': 'p1', 'switchBinding':
              [{'host': 'h1', 'switch': 'switch01', 'segment': [],
                'interface': 'Ethernet1'}]}]),
            ('region/RegionOne/port?portId=p1&id=bm1&type=baremetal',
             'DELETE', [port]),
            ('region/RegionOne/baremetal', 'DELETE', [{'id': 'bm1'}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    def test_plug_dhcp_port_into_network(self, mock_send_api_req):
        segments = [{'segmentation_id': 101,
                     'id': 'segment_id_1',
                     'network_type': 'vlan',
                     'is_dynamic': False}]
        self.drv.plug_port_into_network('vm1', 'h1', 'p1', 'n1', 't1', 'port1',
                                        n_const.DEVICE_OWNER_DHCP, None, None,
                                        None, segments)
        calls = [
            ('region/RegionOne/dhcp?tenantId=t1', 'POST',
             [{'id': 'vm1', 'hostId': 'h1'}]),
            ('region/RegionOne/port', 'POST',
             [{'id': 'p1', 'hosts': ['h1'], 'tenantId': 't1',
               'networkId': 'n1', 'instanceId': 'vm1', 'name': 'port1',
               'instanceType': 'dhcp', 'vlanType': 'allowed'}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    @patch('networking_arista.ml2.rpc.arista_json.AristaRPCWrapperJSON.'
           'get_instance_ports')
    def test_unplug_dhcp_port_from_network(self, mock_get_instance_ports,
                                           mock_send_api_req):
        mock_get_instance_ports.return_value = []
        self.drv.unplug_port_from_network('dhcp1', n_const.DEVICE_OWNER_DHCP,
                                          'h1', 'p1', 'n1', 't1', None, None)
        calls = [
            ('region/RegionOne/port?portId=p1&id=dhcp1&type=dhcp',
             'DELETE',
             [{'id': 'p1', 'hosts': [], 'tenantId': None, 'networkId': None,
               'instanceId': 'dhcp1', 'name': None, 'instanceType': 'dhcp',
               'vlanType': 'allowed'}]),
            ('region/RegionOne/dhcp', 'DELETE',
             [{'id': 'dhcp1'}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    def test_plug_router_port_into_network(self, mock_send_api_req):
        segments = [{'segmentation_id': 101,
                     'id': 'segment_id_1',
                     'network_type': 'vlan',
                     'is_dynamic': False}]
        self.drv.plug_port_into_network('router1', 'h1', 'p1', 'n1', 't1',
                                        'port1',
                                        n_const.DEVICE_OWNER_DVR_INTERFACE,
                                        None, None, None, segments)
        calls = [
            ('region/RegionOne/router?tenantId=t1', 'POST',
             [{'id': 'router1', 'hostId': 'h1'}]),
            ('region/RegionOne/port', 'POST',
             [{'id': 'p1', 'hosts': ['h1'], 'tenantId': 't1',
               'networkId': 'n1', 'instanceId': 'router1', 'name': 'port1',
               'instanceType': 'router', 'vlanType': 'allowed'}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)

    @patch(JSON_SEND_FUNC)
    @patch('networking_arista.ml2.rpc.arista_json.AristaRPCWrapperJSON.'
           'get_instance_ports')
    def test_unplug_router_port_from_network(self, mock_get_instance_ports,
                                             mock_send_api_req):
        mock_get_instance_ports.return_value = []
        self.drv.unplug_port_from_network('router1',
                                          n_const.DEVICE_OWNER_DVR_INTERFACE,
                                          'h1', 'p1', 'n1', 't1', None, None)
        calls = [
            ('region/RegionOne/port?portId=p1&id=router1&type=router',
             'DELETE',
             [{'id': 'p1', 'hosts': [], 'tenantId': None, 'networkId': None,
               'instanceId': 'router1', 'name': None, 'instanceType': 'router',
               'vlanType': 'allowed'}]),
            ('region/RegionOne/router', 'DELETE',
             [{'id': 'router1'}])
        ]
        self._verify_send_api_request_call(mock_send_api_req, calls)
