from lxml import etree
import requests

from regparser.notice.diff import parse_amdpar, find_section, find_subpart
from regparser.notice.diff import new_subpart_added
from regparser.notice.diff import DesignateAmendment
from regparser.notice.address import fetch_addresses
from regparser.notice.sxs import find_section_by_section
from regparser.notice.sxs import build_section_by_section
from regparser.notice.util import spaces_then_remove, swap_emphasis_tags
from regparser.notice import changes
from regparser.tree.xml_parser import reg_text


def build_notice(cfr_title, cfr_part, fr_notice, do_process_xml=True):
    """Given JSON from the federal register, create our notice structure"""
    notice = {'cfr_title': cfr_title, 'cfr_part': cfr_part}
    #   Copy over most fields
    for field in ['abstract', 'action', 'agency_names', 'comments_close_on',
                  'document_number', 'publication_date',
                  'regulation_id_numbers']:
        if fr_notice[field]:
            notice[field] = fr_notice[field]

    if fr_notice['effective_on']:
        notice['effective_on'] = fr_notice['effective_on']
        notice['initial_effective_on'] = fr_notice['effective_on']

    if fr_notice['html_url']:
        notice['fr_url'] = fr_notice['html_url']

    if fr_notice['citation']:
        notice['fr_citation'] = fr_notice['citation']

    notice['fr_volume'] = fr_notice['volume']
    notice['meta'] = {}
    for key in ('dates', 'end_page', 'start_page', 'type'):
        notice['meta'][key] = fr_notice[key]

    if fr_notice['full_text_xml_url'] and do_process_xml:
        notice_str = requests.get(fr_notice['full_text_xml_url']).content
        notice_xml = etree.fromstring(notice_str)
        process_xml(notice, notice_xml)

    return notice


def process_designate_subpart(amendment):
    """ Process the designate amendment if it adds a subpart. """

    if 'Subpart' in amendment.destination:
        subpart_changes = {}

        for label in amendment.labels:
            label_id = '-'.join(label)
            subpart_changes[label_id] = {
                'action': 'DESIGNATE', 'destination': amendment.destination}
        return subpart_changes


def process_new_subpart(notice, subpart_added, par):
    subpart_changes = {}
    subpart_xml = find_subpart(par)
    subpart = reg_text.build_subpart(notice['cfr_part'], subpart_xml)

    for change in changes.create_subpart_amendment(subpart):
        subpart_changes.update(change)
    return subpart_changes


def create_changes(amended_labels, section, notice_changes):
    
    amend_map = changes.match_labels_and_changes(amended_labels, section)

    for label, amendments in amend_map.iteritems():
        for amendment in amendments:
            if amendment['action'] in ['POST', 'PUT']:
                if 'field' in amendment:
                    nodes = changes.create_field_amendment(label, amendment)
                else:
                    nodes = changes.create_add_amendment(amendment)
                for n in nodes:
                    notice_changes.update(n)
            elif amendment['action'] == 'DELETE':
                notice_changes.update({label: {'action': amendment['action']}})
            else:
                print 'NOT HANDLED: %s'  % amendment['action']


def process_amendments(notice, notice_xml):
    """ Process the changes to the regulation that are expressed in the notice.
    """
    context = []
    amends = []
    notice_changes = changes.NoticeChanges()

    for par in notice_xml.xpath('//AMDPAR'):
        amended_labels, context = parse_amdpar(par, context)

        for al in amended_labels:
            if isinstance(al, DesignateAmendment):
                subpart_changes = process_designate_subpart(al)
                if subpart_changes:
                    notice_changes.update(subpart_changes)
            elif new_subpart_added(al):
                notice_changes.update(process_new_subpart(notice, al, par))

        section_xml = find_section(par)
        if section_xml is not None:
            for section in reg_text.build_from_section(
                    notice['cfr_part'], section_xml):
                create_changes(amended_labels, section, notice_changes)
        amends.extend(amended_labels)
    if amends:
        notice['amendments'] = amends
        notice['changes'] = notice_changes.changes


def process_sxs(notice, notice_xml):
    sxs = find_section_by_section(notice_xml)
    sxs = build_section_by_section(sxs, notice['cfr_part'],
                                   notice['meta']['start_page'])
    notice['section_by_section'] = sxs


def process_xml(notice, notice_xml):
    """Pull out relevant fields from the xml and add them to the notice"""

    xml_chunk = notice_xml.xpath('//FURINF/P')
    if xml_chunk:
        notice['contact'] = xml_chunk[0].text

    addresses = fetch_addresses(notice_xml)
    if addresses:
        notice['addresses'] = addresses

    process_sxs(notice, notice_xml)
    process_amendments(notice, notice_xml)
    add_footnotes(notice, notice_xml)

    return notice


def add_footnotes(notice, notice_xml):
    notice['footnotes'] = {}
    for child in notice_xml.xpath('//FTNT/*'):
        spaces_then_remove(child, 'PRTPAGE')
        swap_emphasis_tags(child)

        ref = child.xpath('.//SU')
        if ref:
            child.text = ref[0].tail
            child.remove(ref[0])
            content = child.text
            for cc in child:
                content += etree.tostring(cc)
            content += child.tail
            notice['footnotes'][ref[0].text] = content.strip()
