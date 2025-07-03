from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, send_file
)
import json, os, io
from datetime import datetime
import pandas as pd

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")

# ─── FILES ──────────────────────────────────────────────────────────────
USERS_FILE        = 'users.json'
INCOME_LOG_FILE   = 'income_log.json'
EXPENSE_LOG_FILE  = 'expense_log.json'
BUDGETS_FILE      = 'budgets.json'
ENTRIES_FILE      = 'entries.json'    # unified income+expense store

# ─── UTILITIES ──────────────────────────────────────────────────────────
def load_json(path, default=None):
    if os.path.exists(path):
        with open(path,'r') as f:
            return json.load(f)
    return default() if callable(default) else default

def save_json(path, data):
    with open(path,'w') as f:
        json.dump(data, f, indent=2)

def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d")

# ─── AUTH ────────────────────────────────────────────────────────────────
@app.route('/', methods=['GET','POST'])
def login():
    if request.method=='POST':
        users = load_json(USERS_FILE, default=dict)
        u = request.form['username']
        p = request.form['password']
        if u in users and users[u]['password']==p:
            session.update({
                'user': u,
                'role': users[u]['role'],
                'dept': users[u]['department']
            })
            return redirect(url_for('dashboard'))
        flash("Invalid credentials","danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── DASHBOARD ──────────────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    user = session['user']
    role = session['role']
    dept = session['dept']
    now  = datetime.now()

    # filters
    acct = request.args.get('account', 'Main')
    m    = int(request.args.get('month', now.month))
    y    = int(request.args.get('year',  now.year))

    # load data
    entries = load_json(ENTRIES_FILE, default=list)
    budgets = load_json(BUDGETS_FILE, default=dict)

    # filter entries by auth/filters
    def keep(e):
        if role=='Finance Manager':
            if acct not in ('Main','Building Fund'): return False
            if e['account'] != acct:               return False
        elif role!='Senior Pastor':
            if e['account'] != dept:                return False
        # Senior Pastor sees all
        d = parse_date(e['date'])
        return d.year==y and d.month==m

    month_entries = [e for e in entries if keep(e)]

    total_inc = sum(e['amount'] for e in month_entries if e['type']=='Income')
    total_exp = sum(e['amount'] for e in month_entries if e['type']=='Expense')
    balance   = total_inc - total_exp
    limit     = budgets.get(acct if role=='Finance Manager' else dept, 0.0)
    remaining = limit - total_exp

    # chart data for the year
    labels     = [f"{y}-{mn:02d}" for mn in range(1,13)]
    def sum_for(lbl, t):
        return sum(e['amount'] for e in entries
                   if e['type']==t
                   and (role=='Senior Pastor'
                        or e['account']==(acct if role=='Finance Manager' else dept))
                   and e['date'].startswith(lbl))
    chart_inc = [sum_for(lbl,'Income')  for lbl in labels]
    chart_exp = [sum_for(lbl,'Expense') for lbl in labels]

    return render_template('dashboard.html',
        user=user, role=role, dept=dept,
        now=now, selected_month=m, selected_year=y,
        current_year=now.year, account=acct,
        total_income=total_inc, total_expense=total_exp,
        balance=balance, budget_limit=limit,
        remaining=remaining,
        chart_labels=labels,
        chart_income=chart_inc,
        chart_expense=chart_exp
    )

# ─── ADD INCOME ────────────────────────────────────────────────────────────
@app.route('/add-income', methods=['GET','POST'])
def add_income():
    if 'user' not in session:
        return redirect(url_for('login'))

    role = session['role']
    dept = session['dept']

    # build valid_accounts
    if role == 'Finance Manager':
        valid_accounts = ['Main', 'Building Fund']
    elif role == 'Senior Pastor':
        valid_accounts = []            # view only
    else:
        valid_accounts = [dept]        # departmental treasurers

    if request.method == 'POST':
        # pull from <select name="account">
        acc = request.form['account']

        if acc not in valid_accounts:
            flash("Account not permitted", "danger")
            return redirect(url_for('dashboard'))

        entry = {
            'type':        request.form['type'],
            'account':     acc,
            'department':  dept,
            'description': request.form.get('description',''),
            'date':        request.form['date'],
            'amount':      float(request.form['amount'])
        }
        log = load_json(INCOME_LOG_FILE) or []
        log.append(entry)
        save_json(INCOME_LOG_FILE, log)

        flash("Income saved","success")
        return redirect(url_for('dashboard'))

    # GET → render with required context
    return render_template(
      'add_income.html',
      role=role,
      valid_accounts=valid_accounts,
      now=datetime.now()
    )

# ─── ADD EXPENSE ───────────────────────────────────────────────────────────
@app.route('/add-expense', methods=['GET','POST'])
def add_expense():
    if 'user' not in session:
        return redirect(url_for('login'))

    role = session['role']
    dept = session['dept']

    # Build the list of accounts this user may post to
    if role == 'Finance Manager':
        valid_accounts = ['Main', 'Building Fund']
    elif role == 'Senior Pastor':
        valid_accounts = []            # view-only, no posting
    else:
        valid_accounts = [dept]        # departmental treasurers

    if request.method == 'POST':
        acc = request.form['account']
        if acc not in valid_accounts:
            flash("Account not permitted", "danger")
            return redirect(url_for('dashboard'))

        entry = {
            'type':        'Expense',
            'account':     acc,
            'department':  dept,
            'description': request.form.get('description', ''),
            'date':        request.form['date'],
            'amount':      float(request.form['amount'])
        }
        log = load_json(EXPENSE_LOG_FILE) or []
        log.append(entry)
        save_json(EXPENSE_LOG_FILE, log)

        flash("Expense saved", "success")
        return redirect(url_for('dashboard'))

    # GET → render with exactly the three variables your template needs:
    return render_template(
        'add_expense.html',
        role=role,
        valid_accounts=valid_accounts,
        now=datetime.now()
    )

# ─── BUDGET MANAGEMENT ───────────────────────────────────────────────────
@app.route('/budgets', methods=['GET','POST'])
def manage_budgets():
    if session.get('role')!='Finance Manager':
        return redirect(url_for('dashboard'))

    budgets = load_json(BUDGETS_FILE, default=dict)
    if request.method=='POST':
        for acc in ['Main','Building Fund']:
            try:
                budgets[acc] = float(request.form.get(acc, budgets.get(acc,0)))
            except ValueError:
                pass
        save_json(BUDGETS_FILE, budgets)
        flash("Budgets updated","success")
        return redirect(url_for('manage_budgets'))

    return render_template('manage_budgets.html', budgets=budgets)

# ─── FINANCE REPORT & EXPORT ─────────────────────────────────────────────────

@app.route('/report')
def report():
    # grab filters from querystring
    dept_f = request.args.get('department', '')
    frm    = request.args.get('from_date', '')
    to     = request.args.get('to_date', '')

    # load and tag entries
    incomes  = load_json(INCOME_LOG_FILE)  or []
    expenses = load_json(EXPENSE_LOG_FILE) or []
    for i in incomes:
        i['type']        = 'Income'
        i['description'] = i.get('description', i.get('category', i.get('note', '')))
    for e in expenses:
        e['type']        = 'Expense'
        e['description'] = e.get('description', e.get('category', e.get('note', '')))

    # merge & filter
    combined = incomes + expenses
    def passes(r):
        if dept_f and dept_f.lower() not in r['department'].lower(): return False
        if frm   and r['date']        < frm: return False
        if to    and r['date']        > to:  return False
        return True

    data = [r for r in combined if passes(r)]
    data.sort(key=lambda r: r['date'], reverse=True)

    return render_template(
      'report.html',
      data=data,
      department_filter=dept_f,
      from_date=frm,
      to_date=to
    )


@app.route('/export-excel')
def export_excel():
    # re-use same filtering logic
    dept_f = request.args.get('department', '')
    frm    = request.args.get('from_date', '')
    to     = request.args.get('to_date', '')

    incomes  = load_json(INCOME_LOG_FILE)  or []
    expenses = load_json(EXPENSE_LOG_FILE) or []
    rows = []

    for r in incomes + expenses:
        rtype = 'Income' if r.get('type','').lower()=='income' else 'Expense'
        desc  = r.get('description', r.get('category', r.get('note','')))
        if dept_f and dept_f.lower() not in r['department'].lower(): continue
        if frm   and r['date'] < frm: continue
        if to    and r['date'] > to:  continue

        rows.append({
          'Date':        r['date'],
          'Department':  r['department'],
          'Type':        rtype,
          'Description': desc,
          'Amount (R)':  r['amount']
        })

    df     = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Report')
    output.seek(0)

    fn = f"report_{dept_f or 'all'}_{frm}_{to}.xlsx"
    return send_file(output,
                     download_name=fn,
                     as_attachment=True)


@app.route('/export-pdf')
def export_pdf():
    # same data & filter
    dept_f = request.args.get('department', '')
    frm    = request.args.get('from_date', '')
    to     = request.args.get('to_date', '')

    incomes  = load_json(INCOME_LOG_FILE)  or []
    expenses = load_json(EXPENSE_LOG_FILE) or []
    rows = []

    for r in incomes + expenses:
        rtype = 'Income' if r.get('type','').lower()=='income' else 'Expense'
        desc  = r.get('description', r.get('category', r.get('note','')))
        if dept_f and dept_f.lower() not in r['department'].lower(): continue
        if frm   and r['date'] < frm: continue
        if to    and r['date'] > to:  continue

        rows.append({
          'date':        r['date'],
          'department':  r['department'],
          'type':        rtype,
          'description': desc,
          'amount':      r['amount']
        })

    # most recent first
    rows.sort(key=lambda x: x['date'], reverse=True)
    return render_template(
      'report_pdf.html',
      data=rows,
      now=lambda: datetime.now()
    )


# ─── RUN SERVER ────────────────────────────────────────────────────────────
if __name__=='__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT',10000)),
        debug=True
    )
