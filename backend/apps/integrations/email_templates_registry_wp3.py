"""Broadcast envelopes use the same editable email engine as lifecycle messages."""

from .email_templates_registry_helpers import EmailTemplateRegistryEntry, bag


def build_entries():
    return {('membership', audience, 'broadcast'): EmailTemplateRegistryEntry(
        label='Member broadcast', description='Staff announcement addressed to one member.',
        fields=[{'name': 'announcement.title', 'description': 'Announcement title.'},
                {'name': 'announcement.body', 'description': 'Announcement body.'},
                {'name': 'makerspace.name', 'description': 'Makerspace name.'}],
        default_subject='{{ announcement.title }}', default_text='{{ announcement.body }}', default_html='',
        sample_context={'announcement': bag(title='Workshop update', body='The room opens at nine.'),
                        'makerspace': bag(name='Demo workshop')},
    ) for audience in ('staff', 'requester')}
