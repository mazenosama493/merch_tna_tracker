// List view settings for "Order TNA Tracker"
// Place this file next to order_tna_tracker.js in the doctype folder.

frappe.listview_settings['Order TNA Tracker'] = {
    // Make sure order_status is always fetched for the list rows
    add_fields: ['order_status'],

    // Returns [label, color, filter]; clicking the pill filters the list by that status
    get_indicator: function(doc) {
        const statuses = {
            'Not yet Started': ['Not yet Started', 'orange', 'order_status,=,Not yet Started'],
            'In Progress':     ['In Progress',     'blue', 'order_status,=,In Progress'],
            'Completed':       ['Completed',       'green',  'order_status,=,Completed']
        };

        const match = statuses[doc.order_status];
        if (match) {
            return [__(match[0]), match[1], match[2]];
        }

        // Old records with an empty / unknown status
        return [__(doc.order_status || 'Not Set'), 'gray', 'order_status,=,' + (doc.order_status || '')];
    }
};