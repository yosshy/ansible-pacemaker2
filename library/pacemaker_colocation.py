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
module: pacemaker_colocation
short_description: Set or unset a pacemaker colocation constraint
author:
    - Akira Yoshiyama <akirayoshiyama@gmail.com>
description:
    - Set or unset a pacemaker colocation constratint.
options:
    resource1:
        description:
            - ID of the first resource, append '=master' or '=slave'
              to the ID if required.
    resource2:
        description:
            - ID of the second resource, append '=master' or '=slave'
              to the ID if required.
    score:
        description:
            - Constraint score (-INFINITY .. INFINITY)
        default: INFINITY
    state:
        description:
            - Whether the colocation constratint should be present or absent.
        choices: [ absent, present ]
        default: present
    force:
        description:
            - Force update colocation constratint definition.
        choices: [ yes, no ]
        default: no
'''

EXAMPLES = '''
- name: Add a colocation constratint
  pacemaker_colocation:
    resource1: vip1=master
    resource2: vip2
    state: present

- name: Remove a colocation constratint
  pacemaker_colocation:
    resource1: vip1
    resource2: vip2
    state: absent
'''

import shlex
import subprocess
import traceback
import xml.etree.cElementTree as ET

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_native


def get_cib():
    cmd = ["/usr/sbin/cibadmin", "--query"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    stdout, stderr = p.communicate()
    if p.returncode != 0:
        raise Exception(stderr)
    return ET.fromstring(stdout)


def set_cib_constraints(cib):
    cib_xml = ET.tostring(cib)
    cmd = ["/usr/sbin/cibadmin", "--replace", "--scope", "constraints",
           "--xml-pipe"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    p.communicate(cib_xml)
    if p.returncode != 0:
        raise Exception(stderr)


def append_colocation_node(constraints, res=None, res_role=None,
                           with_res=None, with_res_role=None, score=''):
    attrib = {
        'id': 'colocation-%s-%s-%s' % (res, with_res, score),
        'rsc': res,
        'with-rsc': with_res,
        'score': score,
    }
    if res_role == 'master':
        attrib['res-role'] = 'Master'
    elif res_role == 'slave':
        attrib['res-role'] = 'Slave'
    if with_res_role == 'master':
        attrib['with-res-role'] = 'Master'
    elif with_res_role == 'slave':
        attrib['with-res-role'] = 'Slave'
    return ET.SubElement(constraints, 'rsc_colocation', attrib)


def has_difference(current, new):
    if current.tag != new.tag:
        return True
    if current.tag == 'rsc_colocation':
        if current.attrib != new.attrib:
            if current.get('rsc') == new.get('rsc'):
                return True
            if (current.get('rsc') != new.get('with-rsc') or
                    current.get('with-rsc') != new.get('rsc') or
                    current.get('rsc-role') != new.get('with-rsc-role') or
                    current.get('with-rsc-role') != new.get('rsc-role') or
                    current.get('score') != new.get('score')):
                return True
    else:
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
            resource1=dict(type='str', required=True),
            resource2=dict(type='str', required=True),
            score=dict(type='str', default='INFINITY'),
            state=dict(type='str', default='present',
                       choices=['absent', 'present']),
            force=dict(type='bool', default=None),
        ),
        supports_check_mode=True,
    )

    resource1 = module.params['resource1']
    resource2 = module.params['resource2']
    score = module.params['score']
    state = module.params['state']
    force = module.params['force']

    check_only = module.check_mode

    result = dict(
        resource1=resource1,
        resource2=resource2,
        score=score,
        state=state,
        force=force,
        changed=False
    )

    try:
        cib = get_cib()
        resources = cib.find('.//resources')
        constraints = cib.find('.//constraints')

        if '=' in resource1:
            res, res_role = resource1.split('=', 1)
        else:
            res, res_role = resource1, None
        if '=' in resource2:
            with_res, with_res_role = resource2.split('=', 1)
        else:
            with_res, with_res_role = resource2, None

        if res_role not in ['master', 'slave', None]:
            raise Exception("invalid role for %s: %s" % (res, res_role))
        if with_res_role not in ['master', 'slave', None]:
            raise Exception("invalid role for %s: %s" % (with_res,
                                                         with_res_role))

        if resources.find(".//*[@id='%s']" % res) is None:
            raise Exception("no such resource: %s" % res)
        if resources.find(".//*[@id='%s']" % with_res) is None:
            raise Exception("no such resource: %s" % with_res)

        # Get current colocation constraints
        nodes = \
            constraints.findall(
                ".//rsc_colocation[@rsc='%s'][@with-rsc='%s']" % (
                    res, with_res)) + \
            constraints.findall(
                ".//rsc_colocation[@rsc='%s'][@with-rsc='%s']" % (
                    with_res, res))

        # Add/remove the colocation constraint as needed
        if state == 'absent':
            if len(nodes):
                for node in nodes:
                    constraints.remove(node)
                result['changed'] = True
        else:
            if len(nodes) == 0:
                node = append_colocation_node(constraints, res, res_role,
                                              with_res, with_res_role, score)
                result['changed'] = True
            else:
                new_node = append_colocation_node(constraints, res, res_role,
                                                  with_res, with_res_role,
                                                  score)
                for node in nodes:
                    if has_difference(node, new_node):
                        result['changed'] = True
                        break
                if force or result['changed']:
                    for node in nodes:
                        constraints.remove(node)
                    result['changed'] = True
                else:
                    constraints.remove(new_node)

        # Apply the modified CIB as needed
        if result['changed'] and not check_only:
            set_cib_constraints(constraints)

        # Report the success result and exit
        module.exit_json(**result)

    except Exception as e:

        # Report the failure result and exit
        module.fail_json(msg=to_native(e),
                         exception=traceback.format_exc(),
                         **result)


if __name__ == '__main__':
    main()
