#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2018, Akira Yoshiyama <akirayoshiyama@gmail.com>
# GNU General Public License v3.0+
# (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: pacemaker_resource_default
short_description: Set or unset pacemaker resource defaults
author:
    - Akira Yoshiyama <akirayoshiyama@gmail.com>
description:
    - Set or unset pacemaker resource defaults
options:
    params:
        required: true
        description:
            - resource default parameters in key=value style
    state:
        description:
            - Whether the parameters should be present or absent.
        choices: [ absent, present ]
        default: present
'''

EXAMPLES = '''
- name: Set pacemaker resource defaults
  pacemaker_resource_default:
    params: >
      resource-stickiness=100
      migration-threshold=5
'''

import shlex
import subprocess
import traceback
import xml.etree.cElementTree as ET

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_native


def get_cib_rsc_defaults():
    cmd = ["/usr/sbin/cibadmin", "--query", "--scope", "rsc_defaults"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate()
    if p.returncode != 0:
        raise Exception(stderr)
    return ET.fromstring(stdout)


def set_cib_rsc_defaults(cib):
    cib_xml = ET.tostring(cib)
    cmd = ["/usr/sbin/cibadmin", "--replace", "--scope", "rsc_defaults",
           "--xml-pipe"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate(cib_xml)
    if p.returncode != 0:
        raise Exception(stderr)


def option_str_to_dict(opts):
    if not isinstance(opts, basestring):
        return {}
    opts = opts.replace('\n', ' ')
    ret = {}
    for opt in shlex.split(opts):
        if '=' in opt:
            key, value = opt.split('=', 1)
            if value[0] == '"' and value[-1] == '"':
                value = value.strip('"')
            ret[key] = value
        else:
            raise Exception("non key=value parameter: %s" % opt)
    return ret


def append_nvpair_node(root, parent_id='', name='', value=''):
    node_id = "%s-%s" % (parent_id, name)
    attrib = {'id': node_id, 'name': name, 'value': value}
    node = ET.SubElement(root, "nvpair", attrib)
    return node


def main():
    module = AnsibleModule(
        argument_spec=dict(
            params=dict(type='str', required=True),
            state=dict(type='str', default='present',
                       choices=['absent', 'present']),
        ),
        supports_check_mode=True,
    )

    params = module.params['params']
    state = module.params['state']

    check_only = module.check_mode

    result = dict(
        params=params,
        state=state,
        changed=False
    )

    try:
        rsc_defaults = get_cib_rsc_defaults()
        parent_node = rsc_defaults.find('.//meta_attributes')

        # Get current properties
        nodes = parent_node.findall(".//nvpair")
        nodes_map = {x.get('name'): x for x in nodes}

        # Get ID list from params
        params_dict = option_str_to_dict(params)

        # Add/remove the properties as needed
        if state == 'absent':
            if len(nodes):
                for node in nodes:
                    if node.get(id) in params_dict:
                        parent_node.remove(node)
                result['changed'] = True
        else:
            for name, value in params_dict.items():
                node = nodes_map.get(name)
                if node is None:
                    append_nvpair_node(parent_node,
                                       parent_id='rsc_defaults-options',
                                       name=name, value=value)
                    result['changed'] = True
                else:
                    if node.get('value') != value:
                        node.set('value', value)
                        result['changed'] = True

        # Apply the modified CIB as needed
        if result['changed'] and not check_only:
            set_cib_rsc_defaults(rsc_defaults)

        # Report the success result and exit
        module.exit_json(**result)

    except Exception as e:

        # Report the failure result and exit
        module.fail_json(msg=to_native(e),
                         exception=traceback.format_exc(),
                         **result)


if __name__ == '__main__':
    main()
