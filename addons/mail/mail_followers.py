# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2009-today OpenERP SA (<http://www.openerp.com>)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>
#
##############################################################################
from openerp.osv import osv, fields
from openerp import tools, SUPERUSER_ID
from openerp.tools.translate import _
from openerp.tools.mail import plaintext2html

class mail_followers(osv.Model):
    """ mail_followers holds the data related to the follow mechanism inside
        OpenERP. Partners can choose to follow documents (records) of any kind
        that inherits from mail.thread. Following documents allow to receive
        notifications for new messages.
        A subscription is characterized by:
            :param: res_model: model of the followed objects
            :param: res_id: ID of resource (may be 0 for every objects)
    """
    _name = 'mail.followers'
    _rec_name = 'partner_id'
    _log_access = False
    _description = 'Document Followers'
    _columns = {
        'res_model': fields.char('Related Document Model', size=128,
                        required=True, select=1,
                        help='Model of the followed resource'),
        'res_id': fields.integer('Related Document ID', select=1,
                        help='Id of the followed resource'),
        'partner_id': fields.many2one('res.partner', string='Related Partner',
                        ondelete='cascade', required=True, select=1),
        'subtype_ids': fields.many2many('mail.message.subtype', string='Subtype',
            help="Message subtypes followed, meaning subtypes that will be pushed onto the user's Wall."),
    }


class mail_notification(osv.Model):
    """ Class holding notifications pushed to partners. Followers and partners
        added in 'contacts to notify' receive notifications. """
    _name = 'mail.notification'
    _rec_name = 'partner_id'
    _log_access = False
    _description = 'Notifications'

    _columns = {
        'partner_id': fields.many2one('res.partner', string='Contact',
                        ondelete='cascade', required=True, select=1),
        'read': fields.boolean('Read', select=1),
        'starred': fields.boolean('Starred', select=1,
            help='Starred message that goes into the todo mailbox'),
        'message_id': fields.many2one('mail.message', string='Message',
                        ondelete='cascade', required=True, select=1),
    }

    _defaults = {
        'read': False,
        'starred': False,
    }

    def init(self, cr):
        cr.execute('SELECT indexname FROM pg_indexes WHERE indexname = %s', ('mail_notification_partner_id_read_starred_message_id',))
        if not cr.fetchone():
            cr.execute('CREATE INDEX mail_notification_partner_id_read_starred_message_id ON mail_notification (partner_id, read, starred, message_id)')

    def get_partners_to_notify(self, cr, uid, message, partners_to_notify=None, context=None):
        """ Return the list of partners to notify, based on their preferences.

            :param browse_record message: mail.message to notify
            :param list partners_to_notify: optional list of partner ids restricting
                the notifications to process
        """
        notify_pids = []
        for notification in message.notification_ids:
            if notification.read:
                continue
            partner = notification.partner_id
            # If partners_to_notify specified: restrict to them
            if partners_to_notify and partner.id not in partners_to_notify:
                continue
            # Do not send to partners without email address defined
            if not partner.email:
                continue
            # Do not send to partners having same email address than the author (can cause loops or bounce effect due to messy database)
            if message.author_id and message.author_id.email == partner.email:
                continue
            # Partner does not want to receive any emails or is opt-out
            if partner.notification_email_send == 'none':
                continue
            # Partner wants to receive only emails and comments
            if partner.notification_email_send == 'comment' and message.type not in ('email', 'comment'):
                continue
            # Partner wants to receive only emails
            if partner.notification_email_send == 'email' and message.type != 'email':
                continue
            notify_pids.append(partner.id)
        return notify_pids

    def get_signature_footer(self, cr, uid, user_id, res_model=None, res_id=None, context=None):
        """ Format a standard footer for notification emails (such as pushed messages
            notification or invite emails).
            Format:
                <p>--<br />
                    Administrator
                </p>
                <div>
                    <small>Send by <a ...>Your Company</a> using <a ...>OpenERP</a>.</small> OR
                    <small>Send by Administrator using <a ...>OpenERP</a>.</small>
                </div>
        """
        footer = ""
        if not user_id:
            return footer

        # add user signature
        user = self.pool.get("res.users").browse(cr, SUPERUSER_ID, [user_id], context=context)[0]
        if user.signature:
            signature = plaintext2html(user.signature)
        else:
            signature = "--<br />%s" % user.name
        footer = tools.append_content_to_html(footer, signature, plaintext=False, container_tag='p')

        # add company signature
        if user.company_id:
            company = user.company_id.website and "<a style='color:inherit' href='%s'>%s</a>" % (user.company_id.website, user.company_id.name) or user.company_id.name
        else:
            company = user.name
        signature_company = _('<small>Send by %(company)s using %(openerp)s.</small>') % {
                'company': company,
                'openerp': "<a style='color:inherit' href='https://www.openerp.com/'>OpenERP</a>"
            }
        footer = tools.append_content_to_html(footer, signature_company, plaintext=False, container_tag='div')

        return footer

    def _notify(self, cr, uid, msg_id, partners_to_notify=None, context=None):
        """ Send by email the notification depending on the user preferences

            :param list partners_to_notify: optional list of partner ids restricting
                the notifications to process
        """
        if context is None:
            context = {}
        mail_message_obj = self.pool.get('mail.message')

        # optional list of partners to notify: subscribe them if not already done or update the notification
        if partners_to_notify:
            notifications_to_update = []
            notified_partners = []
            notif_ids = self.search(cr, SUPERUSER_ID, [('message_id', '=', msg_id), ('partner_id', 'in', partners_to_notify)], context=context)
            for notification in self.browse(cr, SUPERUSER_ID, notif_ids, context=context):
                notified_partners.append(notification.partner_id.id)
                notifications_to_update.append(notification.id)
            partners_to_notify = filter(lambda item: item not in notified_partners, partners_to_notify)
            if notifications_to_update:
                self.write(cr, SUPERUSER_ID, notifications_to_update, {'read': False}, context=context)
            mail_message_obj.write(cr, uid, msg_id, {'notified_partner_ids': [(4, id) for id in partners_to_notify]}, context=context)

        # mail_notify_noemail (do not send email) or no partner_ids: do not send, return
        if context.get('mail_notify_noemail'):
            return True
        # browse as SUPERUSER_ID because of access to res_partner not necessarily allowed
        msg = self.pool.get('mail.message').browse(cr, SUPERUSER_ID, msg_id, context=context)
        notify_partner_ids = self.get_partners_to_notify(cr, uid, msg, partners_to_notify=partners_to_notify, context=context)
        if not notify_partner_ids:
            return True

        # add the context in the email
        # TDE FIXME: commented, to be improved in a future branch
        # quote_context = self.pool.get('mail.message').message_quote_context(cr, uid, msg_id, context=context)

        # add signature
        body_html = msg.body
        user_id = msg.author_id and msg.author_id.user_ids and msg.author_id.user_ids[0] and msg.author_id.user_ids[0].id or None
        signature_company = self.get_signature_footer(cr, uid, user_id, res_model=msg.model, res_id=msg.res_id, context=context)
        body_html = tools.append_content_to_html(body_html, signature_company, plaintext=False, container_tag='div')

        references = False
        if msg.parent_id:
            references = msg.parent_id.message_id

        mail_values = {
            'mail_message_id': msg.id,
            'auto_delete': True,
            'body_html': body_html,
            'recipient_ids': [(4, id) for id in notify_partner_ids],
            'references': references,
        }
        if msg.email_from:
            mail_values['email_from'] = msg.email_from
        if msg.reply_to:
            mail_values['reply_to'] = msg.reply_to
        mail_mail = self.pool.get('mail.mail')
        email_notif_id = mail_mail.create(cr, uid, mail_values, context=context)
        try:
            return mail_mail.send(cr, uid, [email_notif_id], context=context)
        except Exception:
            return False
