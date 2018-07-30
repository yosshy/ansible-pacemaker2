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
module: pacemaker_resource
short_description: Set or unset a pacemaker resource
author:
    - Akira Yoshiyama <akirayoshiyama@gmail.com>
description:
    - Set or unset a pacemaker resource
options:
    name:
        required: true
        description:
            - ID of pacemaker resource.
    type:
        description:
            - Name of resource type, in standard:provider:type or type.
    params:
        description:
            - Resource parameters in key=value style.
    op:
        description:
            - List of resource operations in key=value style.
    clone:
        description:
            - Resource is cloned.
        choices: [ yes, no ]
        default: no
    master:
        description:
            - Resource has master/slave state.
        choices: [ yes, no ]
        default: no
    meta:
        description:
            - Resource metadata in key=value style.
    state:
        description:
            - Whether the resource should be present or absent.
        choices: [ absent, present, enabled, disabled ]
        default: present
    force:
        description:
            - Force update resource definition.
        choices: [ yes, no ]
        default: no
'''

EXAMPLES = '''
- name: Add a virtual IP resource
  pacemaker_resource:
    name: vip1
    type: ocf:heartbeat:IPaddr2
    params: ip=192.168.50.206 cidr_netmask=24
    op:
      - monitor interval=20s
      - start timeout=30s

- name: Add a cloned resource
  pacemaker_resource:
    name: sample
    type: ocf:pacemaker:Dummy
    clone: clone-max=2 cloned-node-max=2

- name: Add a master-slave resource
  pacemaker_resource:
    name: ms
    type: ocf:pacemaker:Dummy
    master: master-max=2

- name: Enable a virtual IP resource
  pacemaker_resource:
    name: vip1
    state: enabled

- name: Disable a virtual IP resource
  pacemaker_resource:
    name: vip1
    state: disabled

- name: Remove a virtual IP resource
  pacemaker_resource:
    name: vip1
    state: absent
'''

import shlex
import subprocess
import traceback
import xml.etree.cElementTree as ET

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_native


def get_cib_resources():
    cmd = ["/usr/sbin/cibadmin", "--query", "--scope", "resources"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate()
    if p.returncode != 0:
        raise Exception(stderr)
    return ET.fromstring(stdout)


def set_cib_resources(cib):
    cib_xml = ET.tostring(cib)
    cmd = ["/usr/sbin/cibadmin", "--replace", "--scope", "resources",
           "--xml-pipe"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate(cib_xml)
    if p.returncode != 0:
        raise Exception(stderr)


def is_enabled(res):
    name = res.get('id')
    meta = res.find('./meta_attributes')
    if meta is None:
        return True
    node = meta.find("./nvpair[@name='target-role']")
    if node is None:
        return True
    if node.get('value') != 'Stopped':
        return True
    return False


def set_resource_status(res, enabled=True):
    name = res.get('id')
    meta = res.find('./meta_attributes')
    if meta is not None:
        node = meta.find("./nvpair[@name='target-role']")
    else:
        meta = append_meta_attribute_node(res, parent_id=name)
        node = None
    if enabled:
        if node is not None:
            meta.remove(node)
    else:
        if node is not None:
            node.set('value', 'Stopped')
        else:
            attrib = {
                'id': "%s-meta_attributes-target-role" % name,
                'name': 'target-role',
                'value': 'Stopped'
            }
            ET.SubElement(meta, 'nvpair', attrib)


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
            ret['name'] = opt
    return ret


def append_nvpair_node(root, parent_id='', name='', value=''):
    node_id = "%s-%s" % (parent_id, name)
    attrib = {'id': node_id, 'name': name, 'value': value}
    node = ET.SubElement(root, "nvpair", attrib)
    return node


def append_meta_attribute_node(root, parent_id='', **kwargs):
    node_id = "%s-meta_attributes" % parent_id
    attrib = {'id': node_id}
    node = ET.SubElement(root, "meta_attributes", attrib)
    for name, value in kwargs.items():
        append_nvpair_node(node, parent_id=node_id, name=name, value=value)
    return node


def append_instance_attribute_node(root, parent_id='', **kwargs):
    if len(kwargs) == 0:
        return
    node_id = "%s-instance_attributes" % parent_id
    attrib = {'id': node_id}
    node = ET.SubElement(root, "instance_attributes", attrib)
    for name, value in kwargs.items():
        append_nvpair_node(node, parent_id=node_id, name=name, value=value)
    return node


def append_op_node(root, parent_id='', **kwargs):
    name = kwargs['name']
    interval = kwargs.get('interval', '0s')
    kwargs['interval'] = interval
    kwargs['id'] = "%s-%s-interval-%s" % (parent_id, name, interval)
    node = ET.SubElement(root, "op", kwargs)
    return node


def append_operations_node(root, parent_id='', op=[]):
    node = ET.SubElement(root, "operations")
    for o in op:
        o_dict = option_str_to_dict(o)
        append_op_node(node, parent_id=parent_id, **o_dict)
    return node


def append_resource_node(root, name='', type='', op=[],
                         meta='', params='', **kwargs):
    try:
        c, p, t = type.split(':')
        attrib = {'id': name, 'class': c, 'provider': p, 'type': t}
    except ValueError:
        c, t = type.split(':')
        attrib = {'id': name, 'class': c, 'type': t}
    node = ET.SubElement(root, "primitive", attrib)
    meta_dict = option_str_to_dict(meta)
    if meta_dict:
        append_meta_attribute_node(node, parent_id=name, **meta_dict)
    params_dict = option_str_to_dict(params)
    if params_dict:
        append_instance_attribute_node(node, parent_id=name, **params_dict)
    append_operations_node(node, parent_id=name, op=op)
    return node


def append_clone_node(root, clone=None, name='', **kwargs):
    meta_dict = option_str_to_dict(clone)
    node_id = meta_dict.pop('id', '%s-clone' % name)
    attrib = {'id': node_id}
    node = ET.SubElement(root, "clone", attrib)
    append_meta_attribute_node(node, parent_id=node_id, **meta_dict)
    resource_node = append_resource_node(node, parent_id=node_id, name=name,
                                         **kwargs)
    return node, resource_node


def append_master_node(root, master=None, name='', **kwargs):
    meta_dict = option_str_to_dict(master)
    node_id = meta_dict.pop('id', '%s-master' % name)
    attrib = {'id': node_id}
    node = ET.SubElement(root, "master", attrib)
    resource_node = append_resource_node(node, parent_id=node_id, name=name,
                                         **kwargs)
    append_meta_attribute_node(node, parent_id=node_id, **meta_dict)
    return node, resource_node


def has_difference(current, new):
    if current.tag != new.tag:
        return True
    if current.attrib != new.attrib:
        return True
    for n_child in list(new):
        child_id = n_child.get('id')
        if child_id:
            c_child = current.find("./*[@id='%s']" % child_id)
            if c_child is None or has_difference(c_child, n_child):
                return True
        else:
            for c_child in current.findall("./%s" % n_child.tag):
                if not has_difference(c_child, n_child):
                    break
            else:
                return True
    return False


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            type=dict(type='str'),
            params=dict(type='str'),
            meta=dict(type='str'),
            op=dict(type='list', default=[]),
            clone=dict(type='str'),
            master=dict(type='str'),
            state=dict(type='str', default='present',
                       choices=['absent', 'present', 'enabled', 'disabled']),
            force=dict(type='bool', default=None),
        ),
        supports_check_mode=True,
    )

    name = module.params['name']
    type = module.params['type']
    params = module.params['params']
    meta = module.params['meta']
    op = module.params['op']
    clone = module.params['clone']
    master = module.params['master']
    state = module.params['state']
    force = module.params['force']

    check_only = module.check_mode

    result = dict(
        changed=False,
        name=name,
        type=type,
        params=params,
        meta=meta,
        op=op,
        clone=clone,
        master=master,
        state=state,
        force=force,
    )

    try:
        cib = get_cib_resources()
        node = cib.find('.//primitive[@id="%s"]' % name)
        parent_node = cib.find('.//primitive[@id="%s"]/..' % name)
        grand_node = cib.find('.//primitive[@id="%s"]/../..' % name)

        # Add/remove the resource as needed
        if state == 'absent':
            if node is not None:
                if not check_only:
                    if parent_node.tag in ['clone', 'master']:
                        grand_node.remove(parent_node)
                    else:
                        parent_node.remove(node)
                    set_cib_resources(cib)
                result['changed'] = True

            # Report the success result and exit
            module.exit_json(**result)

        else:
            if node is None:
                if master is not None:
                    parent_node, node = append_master_node(cib,
                                                           **module.params)
                elif clone is not None:
                    parent_node, node = append_clone_node(cib, **module.params)
                else:
                    parent_node, node = append_resource_node(cib,
                                                             **module.params)
                result['changed'] = True
            else:
                if master is not None:
                    if parent_node.tag in ['clone', 'master']:
                        new_parent_node, new_node = append_master_node(
                            grand_node, **module.params)
                        if force or has_difference(parent_node,
                                                   new_parent_node):
                            grand_node.remove(parent_node)
                            node = new_node
                            result['changed'] = True
                        else:
                            grand_node.remove(new_parent_node)
                    else:
                        parent_node.remove(node)
                        append_master_node(parent_node, **module.params)
                        result['changed'] = True
                elif clone is not None:
                    if parent_node.tag in ['clone', 'master']:
                        new_parent_node, new_node = append_clone_node(
                            grand_node, **module.params)
                        if force or has_difference(parent_node,
                                                   new_parent_node):
                            grand_node.remove(parent_node)
                            node = new_node
                            result['changed'] = True
                        else:
                            grand_node.remove(new_parent_node)
                    else:
                        parent_node.remove(node)
                        parent_node, node = append_clone_node(parent_node,
                                                              **module.params)
                        result['changed'] = True
                else:
                    if parent_node.tag in ['clone', 'master']:
                        grand_node.remove(parent_node)
                        append_resource_node(grand_node, **module.params)
                        result['changed'] = True
                    else:
                        new_node = append_resource_node(parent_node,
                                                        **module.params)
                        if force or has_difference(node, new_node):
                            parent_node.remove(node)
                            node = new_node
                            result['changed'] = True
                        else:
                            parent_node.remove(new_node)

        # Start/stop the resource as needed
        enabled = is_enabled(node)
        if state == 'enabled' and not enabled:
            set_resource_status(node, enabled=True)
            result['changed'] = True
        elif state == 'disabled' and enabled:
            set_resource_status(node, enabled=False)
            result['changed'] = True

        # Apply the modified CIB as needed
        if result['changed'] and not check_only:
            set_cib_resources(cib)

        # Report the success result and exit
        module.exit_json(**result)

    except Exception as e:

        # Report the failure result and exit
        module.fail_json(msg=to_native(e),
                         exception=traceback.format_exc(),
                         **result)


if __name__ == '__main__':
    main()
