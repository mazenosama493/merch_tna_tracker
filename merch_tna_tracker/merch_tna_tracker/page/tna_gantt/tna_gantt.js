// Copyright (c) 2026, volt and contributors
// For license information, please see license.txt

// TNA Gantt - custom page that draws the schedule of one "Order TNA Tracker".
//
// The tracker stores one plan date and one actual date per event (no start
// date), so every event is drawn as two bars that start on the Order Received
// Date:
//
//   Plan   (grey)    : Order Received Date -> Plan Date
//   Actual (colour)  : Order Received Date -> Actual Date
//        green  = actual date is on or before the plan date
//        red    = actual date is after the plan date
//        orange stripes = no actual date yet and the plan date has passed
//
// A dark tick marks the plan date on every row, so it is easy to see where a
// red bar crosses it. Open it with:  /desk/tna-gantt/<order name>

(function () {
	const DAY_MS = 86400000;
	const LEFT_WIDTH = 360; // px, must match .tg-left in the CSS below
	// Width of one day cell: wide enough for a label such as "24-Nov"
	const MIN_DAY_WIDTH = 44;
	const MAX_DAY_WIDTH = 64;

	// ------------------------------------------------------------------
	// Date helpers: work with whole "day numbers" so time zones never matter
	// ------------------------------------------------------------------
	function to_day(iso) {
		const p = String(iso).slice(0, 10).split('-').map(Number);
		return Math.round(Date.UTC(p[0], p[1] - 1, p[2]) / DAY_MS);
	}

	function to_iso(day) {
		return new Date(day * DAY_MS).toISOString().slice(0, 10);
	}

	function user_date(day) {
		return frappe.datetime.str_to_user(to_iso(day));
	}

	function esc(value) {
		return frappe.utils.escape_html(value == null ? '' : String(value));
	}

	function locale() {
		return (frappe.boot && frappe.boot.lang) || undefined;
	}

	// ------------------------------------------------------------------
	// Model: turn the tracker doc into rows with a state and a diff
	// ------------------------------------------------------------------
	function build_model(doc, today) {
		const received = to_day(doc.order_received_date);
		const ex_fty = doc.ex_fty_date ? to_day(doc.ex_fty_date) : null;

		const rows = (doc.tna_details || []).map(function (d, i) {
			const plan = d.plan_date ? to_day(d.plan_date) : received + (d.days_offset || 0);
			const actual = d.actual_date ? to_day(d.actual_date) : null;
			const row = { order: i, event: d.event_name || '', plan: plan, actual: actual, notes: d.notes || '' };

			if (actual === null) {
				row.state = today > plan ? 'overdue' : 'pending';
				row.diff = today > plan ? today - plan : 0; // days overdue
			} else {
				row.state = actual > plan ? 'late' : 'ontime';
				row.diff = actual - plan; // > 0 late, 0 on time, < 0 early
			}
			return row;
		});

		rows.sort(function (a, b) {
			return a.plan - b.plan || a.order - b.order;
		});

		const counts = { ontime: 0, late: 0, overdue: 0, pending: 0 };
		rows.forEach(function (r) {
			counts[r.state] += 1;
		});

		const finished = rows.length > 0 && rows.every(function (r) { return r.actual !== null; });

		// Visible range: every date we draw, plus today while the order is still open
		const days = [received];
		if (ex_fty !== null) days.push(ex_fty);
		if (!finished) days.push(today);
		rows.forEach(function (r) {
			days.push(r.plan);
			if (r.actual !== null) days.push(r.actual);
		});

		return {
			rows: rows,
			counts: counts,
			received: received,
			ex_fty: ex_fty,
			today: today,
			finished: finished,
			first: Math.min.apply(null, days) - 1,
			last: Math.max.apply(null, days) + 2
		};
	}

	function chip_for(row) {
		if (row.state === 'late') return { cls: 'tg-late', text: __('{0} d late', [row.diff]) };
		if (row.state === 'ontime') {
			return row.diff === 0
				? { cls: 'tg-ok', text: __('On time') }
				: { cls: 'tg-ok', text: __('{0} d early', [-row.diff]) };
		}
		if (row.state === 'overdue') return { cls: 'tg-overdue', text: __('{0} d overdue', [row.diff]) };
		return { cls: 'tg-pending', text: __('Pending') };
	}

	// ------------------------------------------------------------------
	// Page
	// ------------------------------------------------------------------
	class TNAGantt {
		constructor(page) {
			this.page = page;
			this.current = null;
			this.doc = null;

			this.make_controls();
			this.$container = $('<div class="tg-wrap"></div>').appendTo(page.main);
			this.show_message(__('Select an order to see its TNA Gantt chart.'));

			// Re-fit the chart whenever its container changes width. A plain window
			// resize listener misses "Toggle Full Width", the sidebar toggle and F11.
			const refit = frappe.utils.debounce(() => {
				if (!this.doc || !this.page.wrapper.is(':visible')) return;
				const w = Math.round(this.$container.width());
				if (w > 0 && Math.abs(w - (this.last_width || 0)) >= 2) this.render();
			}, 200);

			if (window.ResizeObserver) {
				this.resize_observer = new window.ResizeObserver(refit);
				this.resize_observer.observe(this.$container[0]);
			} else {
				$(window).on('resize.tna_gantt', refit);
			}
		}

		make_controls() {
			this.order_field = this.page.add_field({
				fieldname: 'order',
				label: __('Order'),
				fieldtype: 'Link',
				options: 'Order TNA Tracker',
				change: () => {
					const value = this.order_field.get_value();
					if (!value) return;
					this.load(value);
					// keep the URL shareable: /desk/tna-gantt/<order>
					if (frappe.get_route()[1] !== value) frappe.set_route('tna-gantt', value);
				}
			});

			this.page.set_secondary_action(
				__('Refresh'),
				() => this.current && this.load(this.current, true),
				'refresh'
			);

			this.page.add_menu_item(__('Open Order'), () => {
				if (this.current) frappe.set_route('Form', 'Order TNA Tracker', this.current);
			});
		}

		load(name, force) {
			if (!name || (name === this.current && !force)) return;
			this.current = name;
			this.show_message(__('Loading...'));

			frappe.call({
				method: 'frappe.client.get',
				args: { doctype: 'Order TNA Tracker', name: name },
				callback: (r) => {
					if (this.current !== name) return; // user already picked another order
					this.doc = r.message;
					this.render();
				},
				error: () => {
					this.current = null;
					this.doc = null;
					this.show_message(__('Could not load {0}.', [name]));
				}
			});
		}

		show_message(text) {
			this.$container.html('<div class="tg-empty">' + esc(text) + '</div>');
		}

		render() {
			const doc = this.doc;
			if (!doc) return;

			let html = this.summary_html(doc);

			if (!doc.order_received_date) {
				html += '<div class="tg-empty">' + esc(__('This order has no Order Received Date.')) + '</div>';
				this.$container.html(html);
				return;
			}

			if (!(doc.tna_details || []).length) {
				html += '<div class="tg-empty">' + esc(__('This order has no TNA events yet.')) + '</div>';
				this.$container.html(html);
				return;
			}

			const model = build_model(doc, to_day(frappe.datetime.get_today()));
			this.last_width = Math.round(this.$container.width());
			const avail = Math.max(this.$container.width() - LEFT_WIDTH - 4, 320);
			const span = model.last - model.first + 1;
			const dw = Math.max(MIN_DAY_WIDTH, Math.min(MAX_DAY_WIDTH, Math.floor(avail / span)));

			html += this.stats_html(model) + this.legend_html() + this.chart_html(model, dw);
			this.$container.html(html);
			this.update_sticky_offset();
			this.bind_scroll();
			this.scroll_to_today(model, dw);
		}

		// ---- summary / stats / legend --------------------------------

		summary_html(doc) {
			const status_color = { 'Not yet Started': 'orange', 'In Progress': 'blue', 'Completed': 'green' };
			const field = function (label, value) {
				if (value == null || value === '') return '';
				return '<div class="tg-field"><small>' + esc(label) + '</small><b>' + value + '</b></div>';
			};

			const status = doc.order_status
				? '<span class="indicator-pill ' + (status_color[doc.order_status] || 'gray') + '">' +
				  esc(__(doc.order_status)) + '</span>'
				: '';
			const dates = doc.order_received_date && doc.ex_fty_date
				? esc(frappe.datetime.str_to_user(doc.order_received_date)) + ' &rarr; ' +
				  esc(frappe.datetime.str_to_user(doc.ex_fty_date))
				: '';

			return (
				'<div class="tg-summary">' +
				field(__('Order'), esc(doc.name)) +
				field(__('Buyer'), esc(doc.buyer)) +
				field(__('Style'), esc(doc.style_no)) +
				field(__('Sales Order'), esc(doc.sales_order)) +
				field(__('Merchant'), esc(doc.merchant)) +
				field(__('Factory'), esc(doc.factory)) +
				field(__('Received → Ex Fty'), dates) +
				field(__('Lead Time'), doc.lead_time != null ? esc(__('{0} days', [doc.lead_time])) : '') +
				field(__('Status'), status) +
				'</div>'
			);
		}

		stats_html(model) {
			const total = model.rows.length;
			const done = model.counts.ontime + model.counts.late;
			const card = function (cls, value, label) {
				return '<div class="tg-stat ' + cls + '"><b>' + value + '</b>' + esc(label) + '</div>';
			};

			return (
				'<div class="tg-stats">' +
				card('tg-s-total', done + ' / ' + total, __('Events completed')) +
				card('tg-s-ok', model.counts.ontime, __('On time / early')) +
				card('tg-s-late', model.counts.late, __('Completed late')) +
				card('tg-s-overdue', model.counts.overdue, __('Overdue, not done')) +
				card('tg-s-pending', model.counts.pending, __('Not due yet')) +
				'</div>'
			);
		}

		legend_html() {
			const item = function (cls, label) {
				return '<span><i class="' + cls + '"></i>' + esc(label) + '</span>';
			};

			return (
				'<div class="tg-legend">' +
				item('tg-plan', __('Plan')) +
				item('tg-ok', __('Actual: on time or early')) +
				item('tg-late', __('Actual: after plan date')) +
				item('tg-open', __('Not done, plan date passed')) +
				'<span><i class="tg-tick-key"></i>' + esc(__('Plan date')) + '</span>' +
				'</div>'
			);
		}

		// ---- chart ----------------------------------------------------
		//
		// Layout (so the header and the scrollbar can stay on screen while the
		// PAGE scrolls, no parent may be a scroll container):
		//   .tg-left   event / plan / actual / diff   (sticky header)
		//   .tg-right  .tg-head-clip   sticky header: the days         (scrolled by JS)
		//              .tg-body-scroll the bars                       (scrolled by touch / trackpad)
		//              .tg-hbar        sticky bottom scrollbar        (what the user drags)
		// The three right-hand parts are kept at the same scrollLeft by bind_scroll().

		chart_html(model, dw) {
			const first = model.first;
			const last = model.last;
			const width = (last - first + 1) * dw;
			const x = function (day) {
				return (day - first) * dw;
			};
			const bar = function (a, b) {
				const from = Math.min(a, b);
				const to = Math.max(a, b);
				return 'left:' + x(from) + 'px;width:' + (to - from + 1) * dw + 'px';
			};

			// -- header: one cell per day labelled like "1-Nov"; the 1st of a month gets a thick divider
			const month_names = {};
			const month_name = function (dt) {
				const key = dt.getUTCFullYear() * 12 + dt.getUTCMonth();
				if (!month_names[key]) {
					month_names[key] = dt.toLocaleDateString(locale(), { month: 'short', timeZone: 'UTC' });
				}
				return month_names[key];
			};

			let days = '';
			let month_lines = '';
			for (let d = first; d <= last; d++) {
				const dt = new Date(d * DAY_MS);
				const is_first = dt.getUTCDate() === 1;
				days += '<div class="tg-day' + (is_first ? ' tg-day-first' : '') +
					(d === model.today ? ' tg-day-today' : '') + '" style="left:' + x(d) + 'px;width:' + dw +
					'px" title="' + esc(user_date(d)) + '">' + dt.getUTCDate() + '-' + esc(month_name(dt)) + '</div>';
				if (is_first && d > first) month_lines += '<div class="tg-msep" style="left:' + x(d) + 'px"></div>';
			}

			// -- vertical markers: today + ex factory date
			const markers = [];
			if (model.today >= first && model.today <= last) {
				markers.push({ cls: 'tg-today', day: model.today, label: __('Today') });
			}
			if (model.ex_fty !== null) {
				markers.push({ cls: 'tg-exfty', day: model.ex_fty, label: __('Ex Fty') });
			}
			markers.sort(function (a, b) { return a.day - b.day; });
			if (markers.length === 2 && markers[0].day === markers[1].day) {
				markers.splice(0, 2, { cls: 'tg-today', day: model.today, label: __('Today') + ' / ' + __('Ex Fty') });
			}

			let flags = '';
			let lines = '';
			markers.forEach(function (m, i) {
				const cx = x(m.day) + dw / 2;
				let side = markers.length === 2 && i === 0 ? 'left' : 'right';
				if (side === 'left' && cx < 60) side = 'right';
				flags += '<div class="tg-flag ' + m.cls + '" style="' +
					(side === 'left'
						? 'left:' + (cx - 2) + 'px;transform:translateX(-100%)'
						: 'left:' + (cx + 2) + 'px') +
					'">' + esc(m.label) + '</div>';
				lines += '<div class="tg-line ' + m.cls + '" style="left:' + (cx - 1) + 'px"></div>';
			});

			// -- rows
			let left_rows = '';
			let tracks = '';
			model.rows.forEach(function (r) {
				const chip = chip_for(r);
				const plan_txt = user_date(r.plan);
				const actual_txt = r.actual !== null ? user_date(r.actual) : '';

				const tip = esc(
					r.event + '\n' +
					__('Plan') + ': ' + plan_txt + '\n' +
					__('Actual') + ': ' + (actual_txt || '-') + '\n' +
					chip.text + (r.notes ? '\n' + r.notes : '')
				);

				left_rows +=
					'<div class="tg-lrow" title="' + tip + '">' +
					'<div class="tg-ev">' + esc(r.event) + '</div>' +
					'<div>' + esc(plan_txt) + '</div>' +
					'<div>' + esc(actual_txt || '-') + '</div>' +
					'<div><span class="tg-chip ' + chip.cls + '">' + esc(chip.text) + '</span></div>' +
					'</div>';

				let actual_bar = '';
				if (r.actual !== null) {
					actual_bar = '<div class="tg-bar tg-actual ' + (r.state === 'late' ? 'tg-late' : 'tg-ok') +
						'" style="' + bar(model.received, r.actual) + '"></div>';
				} else if (r.state === 'overdue') {
					actual_bar = '<div class="tg-bar tg-actual tg-open" style="' + bar(model.received, model.today) + '"></div>';
				}

				tracks +=
					'<div class="tg-track" title="' + tip + '">' +
					'<div class="tg-bar tg-plan" style="' + bar(model.received, r.plan) + '"></div>' +
					actual_bar +
					'<div class="tg-tick" style="left:' + ((r.plan - first + 1) * dw - 1) + 'px"></div>' +
					'</div>';
			});

			return (
				'<div class="tg-chart">' +
				'<div class="tg-left">' +
				'<div class="tg-left-head"><div>' + esc(__('Event')) + '</div><div>' + esc(__('Plan')) +
				'</div><div>' + esc(__('Actual')) + '</div><div>' + esc(__('Diff')) + '</div></div>' +
				left_rows +
				'</div>' +
				'<div class="tg-right">' +
				'<div class="tg-head-clip"><div class="tg-head" style="width:' + width + 'px">' +
				'<div class="tg-markers">' + flags + '</div>' +
				'<div class="tg-days">' + days + '</div>' +
				lines +
				'</div></div>' +
				'<div class="tg-body-scroll"><div class="tg-body" style="width:' + width +
				'px;background-size:' + dw + 'px 100%">' + tracks + month_lines + lines + '</div></div>' +
				'<div class="tg-hbar"><div style="width:' + width + 'px;height:1px"></div></div>' +
				'</div>' +
				'</div>'
			);
		}

		// The header and the bottom scrollbar are separate elements, so keep
		// all three horizontally in step (setting an equal value fires no event,
		// so this cannot loop).
		bind_scroll() {
			const els = [
				this.$container.find('.tg-head-clip')[0],
				this.$container.find('.tg-body-scroll')[0],
				this.$container.find('.tg-hbar')[0]
			].filter(Boolean);
			this.scroll_els = els;

			els.forEach(function (el) {
				el.addEventListener('scroll', function () {
					els.forEach(function (other) {
						if (other !== el && other.scrollLeft !== el.scrollLeft) other.scrollLeft = el.scrollLeft;
					});
				}, { passive: true });
			});
		}

		set_scroll_left(value) {
			(this.scroll_els || []).forEach(function (el) {
				el.scrollLeft = value;
			});
		}

		// Sticky parts must stop just under Frappe's own sticky navbar + page head
		update_sticky_offset() {
			const head = this.page.wrapper.find('.page-head')[0];
			const top = head ? Math.max(0, Math.round(head.getBoundingClientRect().bottom)) : 0;
			this.$container[0].style.setProperty('--tg-sticky-top', top + 'px');
		}

		scroll_to_today(model, dw) {
			const $right = this.$container.find('.tg-body-scroll');
			if (!$right.length) return;

			if (model.today < model.first || model.today > model.last) {
				this.set_scroll_left(0);
				return;
			}
			const cx = (model.today - model.first) * dw + dw / 2;
			this.set_scroll_left(Math.max(0, cx - $right.width() / 2));
		}
	}

	// ------------------------------------------------------------------
	// Styles (injected once; colours follow the Frappe theme where possible)
	// ------------------------------------------------------------------
	const CSS = `
.tg-wrap{--tg-green:#2e7d32;--tg-red:#d32f2f;--tg-orange:#f57c00;--tg-blue:#3542fd;--tg-purple:#7b1fa2;--tg-grid:rgba(120,130,140,.5);--tg-grid-strong:rgba(90,100,110,.9);--tg-head:56px;--tg-row:48px;--tg-sticky-top:0px;font-size:13px}
.tg-wrap *{box-sizing:border-box}
.tg-empty{padding:60px 20px;text-align:center;color:var(--text-muted)}
.tg-summary{display:flex;flex-wrap:wrap;gap:10px 28px;padding:14px 16px;margin-bottom:12px;border:1px solid var(--border-color);border-radius:var(--border-radius-md,8px);background:var(--card-bg,var(--bg-color))}
.tg-field small{display:block;font-size:11px;letter-spacing:.3px;text-transform:uppercase;color:var(--text-muted)}
.tg-field b{font-weight:600;color:var(--text-color)}
.tg-stats{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px}
.tg-stat{flex:1 1 130px;padding:10px 14px;border:1px solid var(--border-color);border-left-width:4px;border-radius:var(--border-radius-md,8px);background:var(--card-bg,var(--bg-color));color:var(--text-muted);font-size:12px}
.tg-stat b{display:block;font-size:20px;line-height:1.3;color:var(--text-color)}
.tg-s-total{border-left-color:var(--tg-blue)}
.tg-s-ok{border-left-color:var(--tg-green)}
.tg-s-late{border-left-color:var(--tg-red)}
.tg-s-overdue{border-left-color:var(--tg-orange)}
.tg-s-pending{border-left-color:var(--gray-400,#a0a8b0)}
.tg-legend{display:flex;flex-wrap:wrap;gap:6px 18px;margin-bottom:10px;font-size:12px;color:var(--text-muted)}
.tg-legend i{display:inline-block;width:22px;height:10px;margin-right:6px;border-radius:5px;vertical-align:middle}
.tg-legend i.tg-plan{background:var(--gray-400,#a0a8b0)}
.tg-legend i.tg-ok{background:var(--tg-green)}
.tg-legend i.tg-late{background:var(--tg-red)}
.tg-legend i.tg-open{background:repeating-linear-gradient(45deg,#f57c00,#f57c00 5px,#ffcc80 5px,#ffcc80 10px)}
.tg-legend i.tg-tick-key{width:3px;height:14px;border-radius:1px;background:var(--text-color);opacity:.6}

/* chart: NO overflow on this box or its parents, otherwise the sticky parts stop working */
.tg-chart{display:flex;align-items:stretch;border:1px solid var(--tg-grid-strong);background:var(--card-bg,var(--bg-color))}
.tg-left{flex:0 0 360px;border-right:2px solid var(--tg-grid-strong)}
.tg-left-head,.tg-lrow{display:grid;grid-template-columns:minmax(0,1fr) 78px 78px 84px;gap:6px;align-items:center;padding:0 12px}
.tg-left-head{position:sticky;top:var(--tg-sticky-top);z-index:2;height:var(--tg-head);align-items:end;padding-bottom:8px;border-bottom:2px solid var(--tg-grid-strong);background:var(--card-bg,var(--bg-color));font-size:12px;font-weight:700;color:var(--text-color)}
.tg-lrow{height:var(--tg-row);border-bottom:1px solid var(--tg-grid);font-size:12px;color:var(--text-color)}
.tg-ev{overflow:hidden;font-weight:600;text-overflow:ellipsis;white-space:nowrap}
.tg-chip{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;color:#fff}
.tg-chip.tg-late{background:var(--tg-red)}
.tg-chip.tg-ok{background:var(--tg-green)}
.tg-chip.tg-overdue{background:var(--tg-orange)}
.tg-chip.tg-pending{border:1px solid var(--tg-grid);background:transparent;color:var(--text-muted)}

.tg-right{flex:1 1 auto;min-width:0}
.tg-head-clip{position:sticky;top:var(--tg-sticky-top);z-index:2;height:var(--tg-head);overflow:hidden;background:var(--card-bg,var(--bg-color))}
.tg-head{position:relative;height:var(--tg-head)}
.tg-markers{position:relative;height:20px}
.tg-days{position:relative;height:36px;border-bottom:2px solid var(--tg-grid-strong)}
.tg-day{position:absolute;top:0;height:34px;line-height:34px;overflow:hidden;text-align:center;white-space:nowrap;border-left:1px solid var(--tg-grid);font-size:11px;font-weight:700;color:var(--text-color)}
.tg-day-first{border-left:2px solid var(--tg-grid-strong)}
.tg-day-today{background:var(--tg-blue);color:#fff;border-left-color:var(--tg-blue)}

.tg-body-scroll{overflow-x:auto;scrollbar-width:none}
.tg-body-scroll::-webkit-scrollbar{display:none}
.tg-body{position:relative;background-image:linear-gradient(to right,var(--tg-grid) 1px,transparent 1px);background-repeat:repeat-x}
.tg-track{position:relative;height:var(--tg-row);border-bottom:1px solid var(--tg-grid)}
.tg-msep{position:absolute;top:0;bottom:0;width:2px;background:var(--tg-grid-strong);pointer-events:none}
.tg-bar{position:absolute;height:13px;border-radius:7px}
.tg-bar.tg-plan{top:7px;background:var(--gray-500,#8a94a0)}
.tg-bar.tg-actual{top:27px}
.tg-bar.tg-ok{background:var(--tg-green)}
.tg-bar.tg-late{background:var(--tg-red)}
.tg-bar.tg-open{background:repeating-linear-gradient(45deg,#f57c00,#f57c00 6px,#ffcc80 6px,#ffcc80 12px)}
.tg-tick{position:absolute;top:3px;bottom:3px;width:2px;border-radius:1px;background:var(--text-color);opacity:.7}
.tg-line{position:absolute;bottom:0;width:2px;pointer-events:none;z-index:1}
.tg-head .tg-line{top:18px}
.tg-body .tg-line{top:0}
.tg-line.tg-today{background:var(--tg-blue)}
.tg-line.tg-exfty{background:var(--tg-purple);opacity:.8}
.tg-flag{position:absolute;top:1px;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;line-height:16px;white-space:nowrap;color:#fff}
.tg-flag.tg-today{background:var(--tg-blue)}
.tg-flag.tg-exfty{background:var(--tg-purple)}

/* horizontal scrollbar that stays at the bottom of the screen */
.tg-hbar{position:sticky;bottom:0;z-index:2;overflow-x:scroll;overflow-y:hidden;background:var(--card-bg,var(--bg-color));box-shadow:0 -2px 0 var(--tg-grid-strong)}
.tg-hbar::-webkit-scrollbar{height:14px}
.tg-hbar::-webkit-scrollbar-track{background:var(--control-bg,rgba(120,130,140,.15))}
.tg-hbar::-webkit-scrollbar-thumb{border:3px solid transparent;border-radius:8px;background:var(--tg-grid-strong);background-clip:content-box}

@media (max-width:767px){.tg-left{flex-basis:300px}.tg-left-head,.tg-lrow{grid-template-columns:minmax(0,1fr) 84px}.tg-left-head>div:nth-child(2),.tg-left-head>div:nth-child(3),.tg-lrow>div:nth-child(2),.tg-lrow>div:nth-child(3){display:none}}
`;

	// ------------------------------------------------------------------
	// Frappe page hooks
	// ------------------------------------------------------------------
	frappe.pages['tna-gantt'].on_page_load = function (wrapper) {
		frappe.dom.set_style(CSS, 'tna-gantt-style');

		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __('TNA Gantt'),
			single_column: true
		});

		wrapper.tna_gantt = new TNAGantt(page);
	};

	frappe.pages['tna-gantt'].on_page_show = function (wrapper) {
		const gantt = wrapper.tna_gantt;
		if (!gantt) return;

		gantt.update_sticky_offset();

		const name = frappe.get_route()[1];
		if (name) {
			gantt.order_field.set_value(name);
			gantt.load(name);
		}
	};
})();