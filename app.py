import sqlite3
import os
import psycopg2
from datetime import datetime
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
# Professional Security Configuration for Vercel & Multi-Platform Deployment
app.secret_key = os.environ.get("SECRET_KEY", "blood_bank_secure_key_2026")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
DATABASE_URL = os.environ.get("DATABASE_URL") # Neon Postgres URL

# Dynamic Database Path for Cross-Platform Support (Laptop & Mobile/Termux)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, 'blood_bank.db')

def get_db_connection():
    if DATABASE_URL:
        # Connect to Neon Postgres (Online)
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    else:
        # Connect to SQLite (Local: Laptop/Termux)
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        return conn

def db_query(query, params=(), commit=False, fetch=False, single=False):
    """Hybrid Query Helper that handles both SQLite (?) and Postgres (%s) syntax"""
    conn = get_db_connection()
    # Convert SQLite '?' to Postgres '%s' if we are online
    if DATABASE_URL:
        # RealDictCursor makes Postgres results work like SQLite dictionaries
        cur = conn.cursor(cursor_factory=RealDictCursor)
        query = query.replace('?', '%s')
    else:
        cur = conn.cursor()
        
    cur.execute(query, params)
    
    res = None
    if fetch:
        if single:
            row = cur.fetchone()
            res = dict(row) if row else None
        else:
            rows = cur.fetchall()
            res = [dict(r) for r in rows] if rows else []
    
    if commit:
        conn.commit()
    
    conn.close()
    return res

def init_db():
    # Only need to create SQLite table locally; Neon works via its own dashboard usually, 
    # but we'll try to sync it here for professional reliability.
    if not DATABASE_URL:
        conn = sqlite3.connect(DB_NAME)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS donors (
                donor_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL UNIQUE,
                blood_group TEXT NOT NULL,
                location TEXT NOT NULL,
                email TEXT,
                password TEXT NOT NULL,
                is_hidden INTEGER DEFAULT 1,
                last_donation TEXT DEFAULT NULL 
            )
        ''')
        try:
            conn.execute('ALTER TABLE donors ADD COLUMN last_donation TEXT DEFAULT NULL')
        except: pass
        conn.commit()
        conn.close()
    else:
        # Initialize Neon Postgres if it's the first run
        db_query('''
            CREATE TABLE IF NOT EXISTS donors (
                donor_id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT NOT NULL UNIQUE,
                blood_group TEXT NOT NULL,
                location TEXT NOT NULL,
                email TEXT,
                password TEXT NOT NULL,
                is_hidden INTEGER DEFAULT 1,
                last_donation TEXT DEFAULT NULL 
            )
        ''', commit=True)

# Ensure Database is initialized on startup
init_db()

# Predefined list of 33 Telangana districts
TELANGANA_DISTRICTS = [
    "Adilabad", "Bhadradri Kothagudem", "Hanumakonda", "Hyderabad", "Jagtial", 
    "Jangaon", "Jayashankar Bhupalpally", "Jogulamba Gadwal", "Kamareddy", 
    "Karimnagar", "Khammam", "Komaram Bheem Asifabad", "Mahabubabad", 
    "Mahabubnagar", "Mancherial", "Medak", "Medchal–Malkajgiri", "Mulugu", 
    "Nagarkurnool", "Nalgonda", "Narayanpet", "Nirmal", "Nizamabad", 
    "Peddapalli", "Rajanna Sircilla", "Rangareddy", "Sangareddy", 
    "Siddipet", "Suryapet", "Vikarabad", "Wanaparthy", "Warangal", "Yadadri Bhuvanagiri"
]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/registration_menu')
def registration_menu():
    return render_template('registration_menu.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Validates 10-digit phone number
        if len(request.form['phone']) != 10:
            flash("Invalid phone number. Please enter exactly 10 digits.", "error")
            return redirect(url_for('register'))
        
        # Validates 6-character password
        if len(request.form['password']) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return redirect(url_for('register'))

        # Validates that the location is an official district
        if request.form['location'] not in TELANGANA_DISTRICTS:
            flash("Please choose a valid district from the list (e.g., Karimnagar, not knr).", "error")
            return redirect(url_for('register'))

        # Check if phone number already exists
        existing_user = db_query('SELECT phone FROM donors WHERE phone=?', (request.form['phone'],), fetch=True, single=True)
        if existing_user:
            flash("The mobile number is already registered.", "error")
            return redirect(url_for('register'))

        session['reg_data'] = request.form
        return render_template('registration_preview.html', data=request.form)
    
    return render_template('new_registration.html', locations=TELANGANA_DISTRICTS)

@app.route('/save_donor', methods=['GET', 'POST'])
def save_donor():
    data = session.get('reg_data')
    if not data:
        return redirect(url_for('register'))
        
    db_query('''
        INSERT INTO donors (name, phone, blood_group, location, email, password, last_donation) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (data['name'], data['phone'], data['blood_group'], data['location'], data.get('email'), data['password'], data.get('last_donation')), commit=True)
    
    flash("Congratulations! You have successfully registered as a donor. Thank you for your kindness.", "success")
    return redirect(url_for('index'))

@app.route('/search', methods=['GET', 'POST'])
def search_donors():
    if request.method == 'POST':
        bg = request.form['blood_group'].strip()
        loc = request.form['location'].strip()
        
        # Get total count safely (handling both SQLite and Postgres dict keys)
        count_data = db_query('''
            SELECT COUNT(*) as count FROM donors 
            WHERE blood_group=? AND (is_hidden=0 OR is_hidden IS NULL)
        ''', (bg,), fetch=True, single=True)
        
        # Consistent access regardless of linter concerns
        count_val = count_data.get('count', 0) if count_data and isinstance(count_data, dict) else 0
        
        if count_val == 0:
            return render_template('search_result.html', bg=bg, loc=loc, exact=[], others=[], no_bg_at_all=True)
            
        # Handle optional location
        if not loc:
            # If no location is specified, get ALL matching donors
            exact = db_query('''
                SELECT * FROM donors 
                WHERE blood_group=? AND (is_hidden=0 OR is_hidden IS NULL)
            ''', (bg,), fetch=True)
            others = []
        else:
            # If location is specified, separate into exact and others
            exact = db_query('''
                SELECT * FROM donors 
                WHERE blood_group=? AND location LIKE ? AND (is_hidden=0 OR is_hidden IS NULL)
            ''', (bg, f"%{loc}%"), fetch=True)
            
            others = db_query('''
                SELECT * FROM donors 
                WHERE blood_group=? AND location NOT LIKE ? AND (is_hidden=0 OR is_hidden IS NULL)
            ''', (bg, f"%{loc}%"), fetch=True)
        
        # Ensure lists are safe for iteration even if db_query was ambiguous
        exact = exact if isinstance(exact, list) else []
        others = others if isinstance(others, list) else []
        
        # Add 'days_ago' info for better donor status view
        today = datetime.now()
        for d in exact + others:
            if isinstance(d, dict) and d.get('last_donation'):
                try:
                    past = datetime.strptime(d['last_donation'], "%Y-%m-%d")
                    diff = (today - past).days
                    d['days_ago'] = f"donated {diff}days ago" if diff > 0 else "donated Today"
                except:
                    d['days_ago'] = "donated Recently"
            else:
                d['days_ago'] = None
        
        return render_template('search_result.html', bg=bg, loc=loc, exact=exact, others=others, no_bg_at_all=False)
    
    return render_template('donor_search.html', locations=TELANGANA_DISTRICTS)
    
@app.route('/modify', methods=['GET', 'POST'])
def modify_login():
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        user = db_query('SELECT * FROM donors WHERE phone=? AND password=?', (phone, password), fetch=True, single=True)
        if user:
            session['user_id'] = user['donor_id'] # Unique ID preserved
            return render_template('edit_details.html', user=user, locations=TELANGANA_DISTRICTS)
        
        flash("Incorrect phone number or password. Please try again.", "error")
        return render_template('login_modify.html')
    return render_template('login_modify.html')

@app.route('/privacy_login', methods=['GET', 'POST'])
def privacy_login():
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        user = db_query('SELECT * FROM donors WHERE phone=? AND password=?', (phone, password), fetch=True, single=True)
        if user:
            # Send user to the confirmation page
            return render_template('privacy_confirm.html', user=user)
        
        flash("Incorrect phone number or password. Access denied.", "error")
        return render_template('login_modify.html')
    return render_template('login_modify.html') # Reuse your existing login UI

@app.route('/toggle_privacy', methods=['POST'])
def toggle_privacy():
    donor_id = request.form['donor_id']
    choice = request.form['choice'] # 'yes' or 'no'
    
    if choice == 'yes':
        # Flip the status: 0 matches visible, 1 matches hidden
        current = db_query('SELECT is_hidden FROM donors WHERE donor_id=?', (donor_id,), fetch=True, single=True)
        new_val = 1 if current and current['is_hidden'] == 0 else 0
        
        db_query('UPDATE donors SET is_hidden = ? WHERE donor_id=?', (new_val, donor_id), commit=True)
        
        msg = "Privacy updated! Your details are now HIDDEN from the search results." if new_val else "Privacy updated! Your details are now VISIBLE to those in need."
        flash(msg, "info")
    
    return redirect(url_for('index'))    

# Admin Portal Implementation
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        pw = request.form['password']
        if pw == ADMIN_PASSWORD: # Use environment variable
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        flash("Incorrect admin password. Access denied.", "error")
        return render_template('admin_login.html')
    return render_template('admin_login.html')

@app.route('/admin_dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    donors_raw = db_query('SELECT * FROM donors', fetch=True)
    donors = donors_raw if isinstance(donors_raw, list) else []
    
    # Add 'days_ago' info for admin view
    today = datetime.now()
    for d in donors:
        if isinstance(d, dict) and d.get('last_donation'):
            try:
                past = datetime.strptime(d['last_donation'], "%Y-%m-%d")
                diff = (today - past).days
                d['days_ago'] = f"donated {diff}days ago" if diff > 0 else "donated Today"
            except:
                d['days_ago'] = "donated Recently"
        else:
            d['days_ago'] = None
    
    # Calculate Stats for the Admin Portal
    total = len(donors)
    
    # Rarest Blood Group (Least count)
    rarest_data = db_query('SELECT blood_group FROM donors GROUP BY blood_group ORDER BY COUNT(*) ASC LIMIT 1', fetch=True, single=True)
    rarest = rarest_data.get('blood_group', "N/A") if rarest_data and isinstance(rarest_data, dict) else "N/A"
    
    # Most Common Blood Group
    common_data = db_query('SELECT blood_group FROM donors GROUP BY blood_group ORDER BY COUNT(*) DESC LIMIT 1', fetch=True, single=True)
    common = common_data.get('blood_group', "N/A") if common_data and isinstance(common_data, dict) else "N/A"
    
    # Top District (Hotspot)
    top_loc_data = db_query('SELECT location FROM donors GROUP BY location ORDER BY COUNT(*) DESC LIMIT 1', fetch=True, single=True)
    top_loc = top_loc_data.get('location', "N/A") if top_loc_data and isinstance(top_loc_data, dict) else "N/A"
    
    stats = {
        'total': total,
        'rarest': rarest,
        'common': common,
        'top_loc': top_loc
    }
    
    return render_template('admin_dashboard.html', donors=donors, stats=stats)

@app.route('/admin_logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/delete/<int:donor_id>', methods=['POST'])
def admin_delete_donor(donor_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    db_query('DELETE FROM donors WHERE donor_id = ?', (donor_id,), commit=True)
    
    flash("Donor record successfully deleted.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/update_donor', methods=['POST'])
def update_donor():
    data = request.form
    donor_id = session.get('user_id')

    # Validates that the location is an official district
    if data['location'] not in TELANGANA_DISTRICTS:
        flash("Update failed. Please select an official district from the list.", "error")
        return redirect(url_for('index'))

    db_query('''
        UPDATE donors 
        SET name=?, phone=?, blood_group=?, location=?, email=?, password=?, last_donation=? 
        WHERE donor_id=?
    ''', (data['name'], data['phone'], data['blood_group'], data['location'], data.get('email'), data['password'], data.get('last_donation'), donor_id), commit=True)
    
    flash("Success! Your donor profile has been updated.", "success")
    return redirect(url_for('index'))

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

if __name__ == '__main__':
    app.run(debug=True, port= 5000, host="0.0.0.0")
