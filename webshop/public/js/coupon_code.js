//// Neoffice — added file (no upstream equivalent). Desk script on Coupon Code: shows
//// gift_card_amount only for a Gift Card coupon, read-only (73119aae66, 2025-02-11). Wired in hooks.py
//// doctype_js — upstream registers no script on Coupon Code.
//// It used to copy the Pricing Rule's discount into the balance and save the card every time the form was opened.
//// The balance is the card's own and the shop's cards of one amount share a rule, so opening a card in the desk gave
//// it back what a sister had spent, or took away what it still held (maintenance#3239). It no longer writes it.
frappe.ui.form.on('Coupon Code', {
    refresh: function(frm) {
        // Show or hide the gift card amount field
        frm.toggle_display('gift_card_amount', frm.doc.coupon_type === 'Gift Card');
        
        // Make the field read-only
        frm.set_df_property('gift_card_amount', 'read_only', 1);
    },
    
    coupon_type: function(frm) {
        // Remove the gift card amount
        if (frm.doc.coupon_type !== 'Gift Card') {
            frm.set_value('gift_card_amount', 0);
            frm.save();
        }
        frm.refresh();
    }
});
