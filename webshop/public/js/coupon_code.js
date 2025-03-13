frappe.ui.form.on('Coupon Code', {
    refresh: function(frm) {
        // Show or hide the gift card amount field
        frm.toggle_display('gift_card_amount', frm.doc.coupon_type === 'Gift Card');
        
        // Rendre le champ read-only
        frm.set_df_property('gift_card_amount', 'read_only', 1);
        
        // Mettre à jour le montant si c'est une gift card avec pricing rule
        if (frm.doc.coupon_type === 'Gift Card' && frm.doc.pricing_rule) {
            frappe.db.get_value('Pricing Rule', frm.doc.pricing_rule, 'discount_amount')
                .then(r => {
                    if (r.message && r.message.discount_amount) {
                        let new_amount = r.message.discount_amount;
                        if (frm.doc.gift_card_amount !== new_amount) {
                            frm.set_value('gift_card_amount', new_amount);
                            // Sauvegarder si la valeur a changé
                            frm.save();
                        }
                    }
                });
        }
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
