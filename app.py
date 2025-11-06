from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_file, abort
)
import os, json, io
from datetime import datetime
import pandas as pd

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")

# ─── DATA FILES ─────────────────────────────────────────────────────────────
USERS_FILE   = 'users.json'
BUDGETS_FILE = 'budgets.json'
ENTRIES_FILE = 'entries.json'   # unified store for both Income & Expense

# ─── UTILITIES ──────────────────────────────────────────────────────────────
def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default() if callable(default) else (default if default is not None else {})

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d")

# ensure files exist with sensible defaults
if not os.path.exists(USERS_FILE):
    save_json(USERS_FILE, {
        "admin": {"password": "admin", "role": "Finance Manager", "department": "Main"},
        "pastor": {"password": "pastor", "role": "Senior Pastor", "department": "Main"}
    })
if not os.path.exists(BUDGETS_FILE):
    save_json(BUDGETS_FILE, {
        "Main": 65000,
        "Building Fund": 15000,
        "Men's Fellowship": 10000,
        "Youth": 2500,
        "Local Sisters Fellowship": 10000,
        "Children Ministry": 500
    })
if not os.path.exists(ENTRIES_FILE):
    save_json(ENTRIES_FILE, [])

# ─── AUTH ──────────────────────────────────────────────────────────────────
@app.route('/', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        users = load_json(USERS_FILE, default=dict)
        u = request.form.get('username','').strip()
        p = request.form.get('password','')
        if u in users and users[u].get('password') == p:
            session.update({
                'user': u,
                'role': users[u].get('role', 'Treasurer'),
                'dept': users[u].get('department', 'Main')
            })
            flash("Welcome back, " + u, "success")
            return redirect(url_for('dashboard'))
        flash("Invalid credentials", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── DASHBOARD ─────────────────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    user = session['user']
    role = session['role']
    dept = session['dept']
    now  = datetime.now()

    acct = request.args.get('account', 'Main')
    try:
        m = int(request.args.get('month', now.month))
        y = int(request.args.get('year', now.year))
    except ValueError:
        m, y = now.month, now.year

    entries = load_json(ENTRIES_FILE, default=list) or []
    budgets = load_json(BUDGETS_FILE, default=dict) or {}

    def keep(e):
        # Finance Manager: may choose 'Main' or 'Building Fund'
        if role == 'Finance Manager':
            if acct not in ('Main','Building Fund'):
                return False
            if e.get('account') != acct:
                return False
        # Department treasurers: only their own dept
        elif role != 'Senior Pastor':
            if e.get('account') != dept:
                return False
        # Senior Pastor sees all
        try:
            d = parse_date(e.get('date'))
        except Exception:
            return False
        return d.year == y and d.month == m

    month_entries = [e for e in entries if keep(e)]

    total_inc = sum(float(e.get('amount',0)) for e in month_entries if e.get('type') == 'Income')
    total_exp = sum(float(e.get('amount',0)) for e in month_entries if e.get('type') == 'Expense')

    # compute budget_limit: if budgets[acct] is a dict with total, prefer that
    key = acct if role == 'Finance Manager' else dept
    raw_budget = budgets.get(key)
    budget_limit = 0.0
    if isinstance(raw_budget, dict):
        budget_limit = float(raw_budget.get('total', 0.0) or 0.0)
        # if no 'total' but has 'items', sum them
        if budget_limit == 0.0 and raw_budget.get('items'):
            try:
                budget_limit = sum(float(v) for v in raw_budget.get('items',{}).values())
            except Exception:
                budget_limit = 0.0
    else:
        try:
            budget_limit = float(raw_budget or 0.0)
        except Exception:
            budget_limit = 0.0

    remaining = budget_limit - total_exp

    # chart data for whole year
    labels = [f"{y}-{mn:02d}" for mn in range(1,13)]
    def sum_for(lbl, kind):
        return sum(
            float(e.get('amount',0))
            for e in entries
            if e.get('type')==kind
            and (role=='Senior Pastor' or e.get('account')==key)
            and str(e.get('date','')).startswith(lbl)
        )

    chart_inc = [sum_for(lbl,'Income') for lbl in labels]
    chart_exp = [sum_for(lbl,'Expense') for lbl in labels]

    return render_template('dashboard.html',
        user=user, role=role, dept=dept, now=now,
        selected_month=m, selected_year=y, current_year=now.year,
        account=acct,
        total_income=round(total_inc,2), total_expense=round(total_exp,2),
        balance=round(total_inc - total_exp,2), budget_limit=round(budget_limit,2),
        remaining=round(remaining,2),
        chart_labels=labels, chart_income=chart_inc, chart_expense=chart_exp,
        budgets=budgets
    )

# ─── ADD INCOME ────────────────────────────────────────────────────────────
@app.route('/add-income', methods=['GET','POST'])
def add_income():
    if 'user' not in session:
        return redirect(url_for('login'))
    role = session['role']; dept = session['dept']
    valid_accounts = ['Main','Building Fund'] if role == 'Finance Manager' else ([] if role=='Senior Pastor' else [dept])

    if request.method == 'POST':
        account = request.form.get('account') if role == 'Finance Manager' else dept
        if account not in valid_accounts:
            flash("Account not permitted", "danger")
            return redirect(url_for('dashboard'))

        try:
            entry = {
                'type': 'Income',
                'subtype': request.form.get('type',''),
                'account': account,
                'department': dept,
                'description': request.form.get('description',''),
                'date': request.form.get('date'),
                'amount': float(request.form.get('amount') or 0)
            }
        except ValueError:
            flash("Invalid amount", "danger")
            return redirect(url_for('add_income'))

        entries = load_json(ENTRIES_FILE, default=list) or []
        entries.append(entry)
        save_json(ENTRIES_FILE, entries)
        flash("Income saved", "success")
        return redirect(url_for('dashboard'))

    return render_template('add_income.html', valid_accounts=valid_accounts, role=role, now=datetime.now())

# ─── ADD EXPENSE ───────────────────────────────────────────────────────────
@app.route('/add-expense', methods=['GET','POST'])
def add_expense():
    if 'user' not in session:
        return redirect(url_for('login'))
    role = session['role']; dept = session['dept']
    valid_accounts = ['Main','Building Fund'] if role == 'Finance Manager' else ([] if role=='Senior Pastor' else [dept])

    if request.method == 'POST':
        account = request.form.get('account') if role == 'Finance Manager' else dept
        if account not in valid_accounts:
            flash("Account not permitted", "danger")
            return redirect(url_for('dashboard'))

        try:
            entry = {
                'type': 'Expense',
                'subtype': request.form.get('type',''),
                'account': account,
                'department': dept,
                'description': request.form.get('description',''),
                'date': request.form.get('date'),
                'amount': float(request.form.get('amount') or 0)
            }
        except ValueError:
            flash("Invalid amount", "danger")
            return redirect(url_for('add_expense'))

        entries = load_json(ENTRIES_FILE, default=list) or []
        entries.append(entry)
        save_json(ENTRIES_FILE, entries)
        flash("Expense saved", "success")
        return redirect(url_for('dashboard'))

    return render_template('add_expense.html', valid_accounts=valid_accounts, role=role, now=datetime.now())

# ─── MANAGE BUDGETS ────────────────────────────────────────────────────────
@app.route('/budgets', methods=['GET','POST'])
def manage_budgets():
    if session.get('role') != 'Finance Manager':
        return redirect(url_for('dashboard'))
    budgets = load_json(BUDGETS_FILE, default=dict) or {}

    if request.method == 'POST':
        text = request.form.get('budgets_json','').strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                save_json(BUDGETS_FILE, parsed)
                flash("Budgets updated", "success")
                return redirect(url_for('manage_budgets'))
            else:
                flash("Submit a JSON object at the top level (dictionary).", "danger")
        except Exception as ex:
            flash(f"Invalid JSON: {ex}", "danger")

    return render_template('manage_budgets.html', budgets=budgets)

# ─── MIGRATE FLAT BUDGETS (temporary helper) ───────────────────────────────
@app.route('/_migrate-flat-budgets')
def migrate_budgets():
    budgets = load_json(BUDGETS_FILE, default=dict) or {}
    changed = False
    new_b = {}
    for k,v in budgets.items():
        if isinstance(v, (int, float, str)) and str(v).strip() != "":
            try:
                new_b[k] = {"total": float(v), "items": {}}
                changed = True
            except Exception:
                new_b[k] = v
        elif isinstance(v, dict):
            new_b[k] = v
        else:
            new_b[k] = v
    if changed:
        save_json(BUDGETS_FILE, new_b)
        return "Migrated flat budgets -> itemised structure. You can remove this route later."
    return "No flat numeric budgets found (no change)."

# ─── REPORT & EXPORT ───────────────────────────────────────────────────────
@app.route('/report')
def report():
    dept_f = request.args.get('department','').strip()
    frm = request.args.get('from_date','').strip()
    to  = request.args.get('to_date','').strip()

    entries = load_json(ENTRIES_FILE, default=list) or []

    def ok(e):
        if dept_f and e.get('department','').lower() != dept_f.lower(): return False
        if frm and e.get('date','') < frm: return False
        if to  and e.get('date','') > to:  return False
        return True

    rows = sorted([e for e in entries if ok(e)], key=lambda x: x.get('date',''), reverse=True)
    return render_template('report.html', data=rows, department_filter=dept_f, from_date=frm, to_date=to)

@app.route('/export-excel')
def export_excel():
    dept_f = request.args.get('department','').strip()
    frm = request.args.get('from_date','').strip()
    to  = request.args.get('to_date','').strip()

    entries = load_json(ENTRIES_FILE, default=list) or []
    rows = []
    for e in entries:
        if dept_f and e.get('department','').lower() != dept_f.lower(): continue
        if frm and e.get('date','') < frm: continue
        if to  and e.get('date','') > to: continue
        rows.append({
            'Date': e.get('date',''),
            'Department': e.get('department',''),
            'Type': e.get('type',''),
            'Subtype': e.get('subtype',''),
            'Description': e.get('description',''),
            'Amount (R)': e.get('amount',0)
        })

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Report')
    output.seek(0)
    fn = f"report_{dept_f or 'all'}_{frm}_{to}.xlsx"
    return send_file(output, download_name=fn, as_attachment=True)

@app.route('/export-pdf')
def export_pdf():
    dept_f = request.args.get('department','').strip()
    frm = request.args.get('from_date','').strip()
    to  = request.args.get('to_date','').strip()
    entries = load_json(ENTRIES_FILE, default=list) or []
    rows = []
    for e in entries:
        if dept_f and e.get('department','').lower() != dept_f.lower(): continue
        if frm and e.get('date','') < frm: continue
        if to  and e.get('date','') > to: continue
        rows.append(e)
    rows.sort(key=lambda x: x.get('date',''), reverse=True)
    return render_template('report_pdf.html', data=rows, now=datetime.now())

# ─── DEBUG: show current JSON files (optional, remove in production) ───────
@app.route('/_debug-files')
def debug_files():
    if session.get('role') != 'Finance Manager':
        abort(403)
    return {
        "users": load_json(USERS_FILE, default=dict),
        "budgets": load_json(BUDGETS_FILE, default=dict),
        "entries_count": len(load_json(ENTRIES_FILE, default=list) or [])
    }

# ─── RUN ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',10000)), debug=True)
