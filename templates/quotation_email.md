# Quotation Email - DRAFT

> **This is a draft. It is not sent by the copilot.**
> An estimator reviews the quote, approves it, and sends it themselves (NFR-1).

**To:** {{ initiator_name }} <{{ initiator_email }}>
*(the specific person who initiated the request in the queue - Kellan, Matt,
Rebecca or Tina. Never a group email. They deal with the customer.)*

**Subject:** CBC Quotation {{ quote_number }} - {{ project_name }}{% if bid_due_date %} (bid due {{ bid_due_date }}){% endif %}

---

Hi {{ initiator_first_name }},

Quotation **{{ quote_number }}** for **{{ project_name }}**{% if project_location %}, {{ project_location }}{% endif %} is attached.

- **{{ opening_count }}** openings quoted{% if accessories_count %}, plus {{ accessories_count }} restroom accessory lines{% endif %}{% if frp_in_scope %}, plus FRP wall panels{% endif %}
- Total: **${{ grand_total }}**
- Supply-only material. HP purchase order required. Valid 30 days.
- Freight: TBD - handled when the quote becomes a job.

{% if flags %}
## Needs your attention before this goes out

{% for flag in flags %}
- **{{ flag.severity | upper }}** - {{ flag.note }}{% if flag.opening %} (opening {{ flag.opening }}){% endif %}{% if flag.source_page %}, drawing p.{{ flag.source_page }}{% endif %}
{% endfor %}
{% endif %}

{% if manual_lines %}
## Lines that need a manual price

{% for line in manual_lines %}
- {{ line.description }}{% if line.vendor %} ({{ line.vendor }}){% endif %} - {{ line.reason }}
{% endfor %}
{% endif %}

{% if out_of_scope %}
## Found in the bid set but NOT quoted

{% for item in out_of_scope %}
- {{ item.item }} - {{ item.reason }}{% if item.source_page %} (p.{{ item.source_page }}){% endif %}
{% endfor %}

Worth telling the GC what CBC is not covering.
{% endif %}

{% if rfis %}
## Suggested RFIs

{% for rfi in rfis %}
- {{ rfi }}
{% endfor %}
{% endif %}

Thanks,
{{ estimator_name }}
CBC Estimating - The Hamilton Parker Company

---

**Attachments:** `quotation.pdf`{% if include_review %}, `review_summary.html`{% endif %}
