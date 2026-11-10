frappe.ui.form.on('TNA Plan Template', {
    onload: function(frm) {
        if (frm.is_new() && (!frm.doc.events || frm.doc.events.length === 0)) {
            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'TNA Event',
                    filters: { 'is_active': 1 },
                    fields: ['name', 'sequence'],
                    order_by: 'sequence asc',
                    limit_page_length: 100
                },
                callback: function(r) {
                    if (r.message && r.message.length > 0) {
                        frm.clear_table('events');
                        r.message.forEach(function(ev) {
                            let row = frm.add_child('events');
                            row.event_name = ev.name;
                            row.days_offset = 0;
                        });
                        frm.refresh_field('events');
                    }
                }
            });
        }
    }
});