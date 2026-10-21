"""Client-scoped history filters, using the status labels shown on the dashboard."""
from django.core.paginator import Paginator
from urllib.parse import urlencode


def history_context(history, params):
    rows = list(history.order_by('-created_at', '-pk'))
    def period(row):
        return f'M{row.filing_month:02d}' if row.filing_month else f'Q{row.filing_quarter}'
    extractors = {'form': lambda r: r.form_code, 'status': lambda r: r.operational_status,
                  'year': lambda r: str(r.filing_year), 'period': period}
    labels = {'form': 'Form', 'status': 'Status', 'year': 'Filing year', 'period': 'Month / quarter'}
    from calendar import month_name
    fields = []
    selected = {}
    for key, extract in extractors.items():
        values = sorted({extract(r) for r in rows}, reverse=key == 'year')
        value = params.get('history_' + key, '')
        selected[key] = value
        choices = [(v, month_name[int(v[1:])] if key == 'period' and v.startswith('M') else
                    ('Quarter ' + v[1:] if key == 'period' and v.startswith('Q') else v)) for v in values]
        fields.append({'name': 'history_' + key, 'label': labels[key], 'value': value, 'choices': choices})
    matches = [r for r in rows if all(not selected[k] or extract(r) == selected[k] for k, extract in extractors.items())]
    page = Paginator(matches, 25).get_page(params.get('page'))
    query = urlencode({'tab': 'history', **{'history_' + k: v for k,v in selected.items() if v}})
    return {'orders': page, 'history_page': page, 'history_fields': fields,
            'history_filtered': any(selected.values()), 'history_count': len(matches),
            'history_query': query}
