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
module: pacemaker_resource_group
short_description: Set or unset a pacemaker resource group
author:
    - Akira Yoshiyama <akirayoshiyama@gmail.com>
description:
    - Set or unset a pacemaker resource group
options:
    name:
        required: true
        description:
            - ID of pacemaker resource group.
    resource:
        description:
            - List of resource names.
    state:
        description:
            - Whether the resource should be present or absent.
        choices: [ absent, present, enabled, disabled ]
        default: present
'''

EXAMPLES = '''
- name: Add a resource group
  pacemaker_resource_group:
    name: vips
    resource:
      - vip2
      - vip1

- name: Remove a resource group
  pacemaker_resource_group:
    name: vips
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


def set_group_status(root, enabled=True):
    name = root.get('id')
    meta = root.find('./meta_attributes')
    if meta is not None:
        node = meta.find("./nvpair[@name='target-role']")
    else:
        meta = append_meta_attribute_node(root, parent_id=name)
        node = None
    if enabled:
        if node is not None:
            if node.get('value') == 'Stopped':
                meta.remove(node)
                return True
    else:
        if node is None:
            attrib = {
                'id': "%s-meta_attributes-target-role" % name,
                'name': 'target-role',
                'value': 'Stopped'
            }
            ET.SubElement(meta, 'nvpair', attrib)
            return True
        else:
            if node.get('value') != 'Stopped':
                node.set('value', 'Stopped')
                return True
    return False


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


def append_group_node(root, name='', resource=[], meta='', remove=False,
                      **kwargs):
    attrib = {'id': name}
    node = ET.SubElement(root, 'group', attrib)
    for resource_name in resource:
        resource_node = root.find(".//*[@id='%s']" % resource_name)
        parent_node = root.find(".//*[@id='%s']/.." % resource_name)
        if resource_node is not None:
            node.append(resource_node)
            if remove:
                parent_node.remove(resource_node)
    meta_dict = option_str_to_dict(meta)
    append_meta_attribute_node(node, name, **meta_dict)
    return node


def has_difference(current, new):
    if current.tag != new.tag:
        return True
    if current.attrib != new.attrib:
        return True
    if current.tag == 'group':
        c_children = [x for x in list(current) if x.tag == 'primitive']
        n_children = [x for x in list(new) if x.tag == 'primitive']
        if len(c_children) != len(n_children):
            return True
        for index, c_child in enumerate(c_children):
            if has_difference(c_child, n_children[index]):
                return True
        else:
            return False

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
            resource=dict(type='list', default=[]),
            meta=dict(type='str'),
            state=dict(type='str', default='present',
                       choices=['absent', 'present', 'enabled', 'disabled']),
            force=dict(type='bool', default=False),
        ),
        supports_check_mode=True,
    )

    name = module.params['name']
    resource = module.params['resource']
    meta = module.params['meta']
    state = module.params['state']
    force = module.params['force']

    check_only = module.check_mode

    result = dict(
        changed=False,
        name=name,
        resource=resource,
        meta=meta,
        state=state,
        force=force,
    )

    try:
        cib = get_cib_resources()
        node = cib.find(".//group[@id='%s']" % name)
        parent_node = cib.find(".//group[@id='%s']/.." % name)

        # Add/remove the resource group as needed
        if state == 'absent':
            if node is not None:
                result['changed'] = True
                if not check_only:
                    resource_nodes = [x for x in list(node)
                                      if x.tag == 'primitive']
                    for resource_node in resource_nodes:
                        parent_node.append(resource_node)
                    parent_node.remove(node)
                    set_cib_resources(cib)

            # Report the success result and exit
            module.exit_json(**result)
        else:
            if node is None:
                node = append_group_node(cib, remove=True, **module.params)
                result['changed'] = True
            else:
                new_node = append_group_node(parent_node, **module.params)
                if force or has_difference(node, new_node):
                    parent_node.remove(node)
                    node = new_node
                    result['changed'] = True
                else:
                    parent_node.remove(new_node)

        # Start/stop the resource as needed
        if state == "enabled":
            if set_group_status(node, enabled=True):
                result['changed'] = True
        elif state == "disabled":
            if set_group_status(node, enabled=False):
                result['changed'] = True

        # Apply the modified CIB as needed
        if not check_only and result['changed']:
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
