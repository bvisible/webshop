frappe.ready(() => {
	//// Neoffice — the words come from the server (window.webshop_inquiry, item_inquiry.html), each with its
	//// English as a fallback; the Subject field is gone: the server names the product (create_lead_for_item_inquiry).
	const words = window.webshop_inquiry || {};
	const say = (key, english) => words[key] || __(english);
	let item = null;
	let token = '';
	const d = new frappe.ui.Dialog({
		title: say('title', 'A question about this product'),  //// Neoffice — the server's words, see above
		fields: [
			{
				fieldtype: 'Data',
				label: say('full_name', 'Your name'),  //// Neoffice — the server's words, see above
				fieldname: 'lead_name',
				reqd: 1
			},
			{
				fieldtype: 'Data',
				label: say('company', 'Company (optional)'),  //// Neoffice — the server's words, see above
				fieldname: 'company_name',
			},
			{
				fieldtype: 'Data',
				label: say('email', 'Your e-mail address'),  //// Neoffice — the server's words, see above
				//// Neoffice — the e-mail or the phone, one of the two: checked on sending and by the server
				description: say('either', 'Your e-mail address or your phone number: the shop needs one of the two to answer you.'),
				fieldname: 'email_id',
				options: 'Email'
			},
			{
				fieldtype: 'Data',
				label: say('phone', 'Your phone number'),  //// Neoffice — the server's words, see above
				fieldname: 'phone',
				options: 'Phone'
			},
			//// Neoffice — no Subject field any more: the server names the product
			{
				fieldtype: 'Text',
				label: say('message', 'Your question'),  //// Neoffice — the server's words, see above
				fieldname: 'message',
				reqd: 1
			}
		],
		primary_action: send_inquiry,
		primary_action_label: say('send', 'Send')  //// Neoffice — the server's words, see above
	});

	//// Neoffice — the dialog closes once the message is in, and says so; it used to close at the click and say
	//// nothing, sent or not. The product and the token of the theme's message door go with it.
	function send_inquiry() {
		const values = d.get_values();
		if (!values) return;
		//// Neoffice — the e-mail or the phone, one of the two (the server refuses a question with neither)
		if (!values.email_id && !values.phone) {
			frappe.msgprint(say('either', 'Your e-mail address or your phone number: the shop needs one of the two to answer you.'));
			return;
		}
		const lead = {
			lead_name: values.lead_name,
			company_name: values.company_name,
			email_id: values.email_id,
			phone: values.phone
		};
		d.get_primary_btn().prop('disabled', true);
		frappe.call({
			method: 'webshop.webshop.shopping_cart.cart.create_lead_for_item_inquiry',
			args: { lead: lead, subject: '', message: values.message, item: item, token: token },
			callback: (r) => {
				if (r.exc) return;
				d.hide();
				d.clear();
				//// Neoffice — no promise of a mail: a phone may be all the visitor left
				frappe.msgprint(say('sent', 'Thank you, your question has been sent. The shop will get back to you.'));
			},
			always: () => d.get_primary_btn().prop('disabled', false)
		});
	}

	//// Neoffice — a single-use token, taken when the dialog opens (the theme holds back a message without one).
	function take_token() {
		token = '';
		frappe.call({
			method: 'webshop.webshop.shopping_cart.cart.item_inquiry_token',
			callback: (r) => { token = r.message || ''; }
		});
	}

	$('.btn-inquiry').click((e) => {
		//// Neoffice — the button's own data, not the target's: a click on its inner label gave no product.
		item = $(e.currentTarget).data('item-code');
		take_token();
		if (!['Administrator', 'Guest'].includes(frappe.session.user)) {
			d.set_value('email_id', frappe.session.user);
			d.set_value('lead_name', frappe.get_cookie('full_name'));
		}

		d.show();
	});
});
