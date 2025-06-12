import sqlite3
import time
import subprocess
from datetime import datetime
import threading
import tkinter as tk
from tkinter import ttk
import asyncio

# Add matplotlib imports
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime


DB_FILE = "ping_log.db"
PING_HOST = "8.8.8.8"  # Google DNS, change if needed
PING_INTERVAL = 1  # seconds
REFRESH_INTERVAL = 500  # milliseconds for GUI refresh
CART_LIMIT = 50  # Limit for chart data points
LOGS_LIMIT = 20  # Limit for logs in the table

def ping(host):
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        success = result.returncode == 0
        latency = None
        if success:
            for line in result.stdout.splitlines():
                if "time=" in line:
                    latency = float(line.split("time=")[-1].split()[0])
                    break
        return success, latency
    except Exception as e:
        return False, None

def log_to_sqlite(timestamp, success, latency):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS ping_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            success INTEGER,
            latency_ms REAL
        )
    """)
    c.execute(
        "INSERT INTO ping_log (timestamp, success, latency_ms) VALUES (?, ?, ?)",
        (timestamp, int(success), latency)
    )
    conn.commit()
    conn.close()

def fetch_latest_logs(limit=20):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, timestamp, success, latency_ms FROM ping_log ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows[::-1]  # reverse to show oldest first

def fetch_latest_logs_for_chart(limit=50):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Fetch both success and fail logs
    c.execute("SELECT timestamp, success, latency_ms FROM ping_log ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    # Reverse to show oldest first and set latency to 0 if fail
    processed = []
    for t, success, latency in rows[::-1]:
        if not success:
            latency = -100  # Use -100 to indicate failure in the chart
        processed.append((t, latency))
    return processed

def fetch_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM ping_log WHERE success=1")
    success = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM ping_log WHERE success=0")
    fail = c.fetchone()[0]

    total = success+ fail  # Ensure total is the sum of success and fail
    
    conn.close()
    percent_success = (success / total * 100) if total > 0 else 0
    return total, success, fail, percent_success

def fetch_fail_logs(limit=20):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, timestamp, success, latency_ms FROM ping_log WHERE success=0 ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows[::-1]  # reverse to show oldest first

def save_settings_to_db(ping_interval, refresh_interval, cart_limit, logs_limit):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            ping_interval REAL,
            refresh_interval INTEGER,
            cart_limit INTEGER,
            logs_limit INTEGER
        )
    """)
    # Always keep only one row (id=1)
    c.execute("""
        INSERT INTO settings (id, ping_interval, refresh_interval, cart_limit, logs_limit)
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            ping_interval=excluded.ping_interval,
            refresh_interval=excluded.refresh_interval,
            cart_limit=excluded.cart_limit,
            logs_limit=excluded.logs_limit
    """, (ping_interval, refresh_interval, cart_limit, logs_limit))
    conn.commit()
    conn.close()

def load_settings_from_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            ping_interval REAL,
            refresh_interval INTEGER,
            cart_limit INTEGER,
            logs_limit INTEGER
        )
    """)
    c.execute("SELECT ping_interval, refresh_interval, cart_limit, logs_limit FROM settings WHERE id=1")
    row = c.fetchone()
    conn.close()
    if row and all(x is not None for x in row):
        return float(row[0]), int(row[1]), int(row[2]), int(row[3])
    else:
        return PING_INTERVAL, REFRESH_INTERVAL, CART_LIMIT, LOGS_LIMIT
    
class PingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ping Monitor")
        self.geometry("1000x850")
        self.resizable(True, True)

        # Main content frame (left)
        main_frame = tk.Frame(self)
        main_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Settings frame (right)
        self.settings_frame = tk.Frame(self, relief=tk.RIDGE, borderwidth=2, width=300)
        self.settings_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
        self.settings_frame.pack_propagate(False)  # Prevent frame from shrinking below width

        tk.Label(self.settings_frame, text="Settings", font=("Arial", 14, "bold")).pack(pady=(10, 20))

        tk.Label(self.settings_frame, text="Ping Interval (s):", font=("Arial", 12)).pack(anchor="w")
        self.ping_interval_var = tk.StringVar(value=str(PING_INTERVAL))
        ping_entry = tk.Entry(self.settings_frame, textvariable=self.ping_interval_var)
        ping_entry.pack(pady=(0, 10), anchor="w", fill="x")

        tk.Label(self.settings_frame, text="Refresh Interval (ms):", font=("Arial", 12)).pack(anchor="w")
        self.refresh_interval_var = tk.StringVar(value=str(REFRESH_INTERVAL))
        refresh_entry = tk.Entry(self.settings_frame, textvariable=self.refresh_interval_var)
        refresh_entry.pack(pady=(0, 10), anchor="w", fill="x")

        tk.Label(self.settings_frame, text="Chart Limit:", font=("Arial", 12)).pack(anchor="w")
        self.cart_limit_var = tk.StringVar(value=str(CART_LIMIT))
        cart_entry = tk.Entry(self.settings_frame, textvariable=self.cart_limit_var)
        cart_entry.pack(pady=(0, 10), anchor="w", fill="x")

        tk.Label(self.settings_frame, text="Logs Limit:", font=("Arial", 12)).pack(anchor="w")
        self.logs_limit_var = tk.StringVar(value=str(LOGS_LIMIT))
        logs_entry = tk.Entry(self.settings_frame, textvariable=self.logs_limit_var)
        logs_entry.pack(pady=(0, 10), anchor="w", fill="x")

        confirm_btn = tk.Button(self.settings_frame, text="Confirm", command=self.update_intervals, bg="#4CAF50", fg="white")
        confirm_btn.pack(pady=(20, 10))

        self.status_label = tk.Label(self.settings_frame, text="", fg="blue", font=("Arial", 10))
        self.status_label.pack()

        # Button to show/hide settings
        self.toggle_btn = tk.Button(self, text="<", command=self.toggle_settings)
        self.toggle_btn.place(relx=0.97, rely=0.02, anchor="ne")  # Place at top-right, outside settings_frame

        # Statistics frame
        stats_frame = tk.Frame(main_frame)
        stats_frame.pack(fill=tk.X, padx=10, pady=(10, 0))

        self.total_label = tk.Label(stats_frame, text="Total: 0", font=("Arial", 12))
        self.total_label.pack(side=tk.LEFT, padx=10)
        self.success_label = tk.Label(stats_frame, text="Success: 0", font=("Arial", 12), fg="green")
        self.success_label.pack(side=tk.LEFT, padx=10)
        self.fail_label = tk.Label(stats_frame, text="Fail: 0", font=("Arial", 12), fg="red")
        self.fail_label.pack(side=tk.LEFT, padx=10)
        self.percent_label = tk.Label(stats_frame, text="Success %: 0.00%", font=("Arial", 12))
        self.percent_label.pack(side=tk.LEFT, padx=10)

        # Statistics frame2
        stats_frame2 = tk.Frame(main_frame)
        stats_frame2.pack(fill=tk.X, padx=10, pady=(10, 0))
        self.rap = tk.Label(stats_frame2, text="Recent average ping: 0.00ms", font=("Arial", 12))
        self.rap.pack(side=tk.LEFT, padx=10)

        # Chart frame
        chart_frame = tk.Frame(main_frame)
        chart_frame.pack(fill=tk.BOTH, expand=False, padx=10, pady=(10, 0))

        # Matplotlib Figure
        self.fig, self.ax = plt.subplots(figsize=(6, 2.5), dpi=100)
        self.ax.set_title("Latency Over Time")
        self.ax.set_xlabel("Time")
        self.ax.set_ylabel("Latency (ms)")
        self.fig.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Tooltip label for chart
        self.tooltip = tk.Label(self, text="", bg="yellow", font=("Arial", 10), relief="solid", bd=1)
        self.tooltip.place_forget()

        # Connect matplotlib event for hover
        self.canvas.mpl_connect("motion_notify_event", self.on_chart_hover)

        # Table frame for all logs
        table_frame = tk.Frame(main_frame)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ("id", "timestamp", "success", "latency_ms")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.tree.heading("id", text="ID")
        self.tree.heading("timestamp", text="Timestamp")
        self.tree.heading("success", text="Success")
        self.tree.heading("latency_ms", text="Latency (ms)")
        self.tree.column("id", width=60)
        self.tree.column("timestamp", width=200)
        self.tree.column("success", width=80)
        self.tree.column("latency_ms", width=100)
        self.tree.pack(fill=tk.BOTH, expand=True)

        # Table frame for fail logs only
        fail_table_label = tk.Label(main_frame, text="Failed Pings", font=("Arial", 12, "bold"), fg="red")
        fail_table_label.pack(pady=(5, 0))
        fail_table_frame = tk.Frame(main_frame)
        fail_table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.fail_tree = ttk.Treeview(fail_table_frame, columns=columns, show="headings")
        self.fail_tree.heading("id", text="ID")
        self.fail_tree.heading("timestamp", text="Timestamp")
        self.fail_tree.heading("success", text="Success")
        self.fail_tree.heading("latency_ms", text="Latency (ms)")
        self.fail_tree.column("id", width=60)
        self.fail_tree.column("timestamp", width=200)
        self.fail_tree.column("success", width=80)
        self.fail_tree.column("latency_ms", width=100)
        self.fail_tree.pack(fill=tk.BOTH, expand=True)

        # Define tag styles for coloring
        self.tree.tag_configure("success", foreground="green")
        self.tree.tag_configure("fail", foreground="red")
        self.fail_tree.tag_configure("fail", foreground="red")

        self.after(REFRESH_INTERVAL, self.refresh_table_and_chart)
        
        # Ensure app termination on close
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def toggle_settings(self):
        if self.settings_frame.winfo_ismapped():
            self.settings_frame.pack_forget()
            self.toggle_btn.config(text=">")
        else:
            self.settings_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
            self.toggle_btn.config(text="<")
        # Always keep toggle_btn at the same place
        self.toggle_btn.place(relx=0.97, rely=0.02, anchor="ne")

    def on_chart_hover(self, event):
        # Only show tooltip if mouse is over a point
        if event.inaxes == self.ax and hasattr(self, "chart_points"):
            xdata = event.xdata
            ydata = event.ydata
            if xdata is None or ydata is None:
                self.tooltip.place_forget()
                return
            # Find the closest point
            min_dist = float("inf")
            closest = None
            for (x, y, t) in self.chart_points:
                dist = ((mdates.date2num(x) - xdata) ** 2 + (y - ydata) ** 2) ** 0.5
                if dist < min_dist:
                    min_dist = dist
                    closest = (x, y, t)
            # Only show tooltip if mouse is very close to the point
            if closest and min_dist < 0.1:
                latency = closest[1]
                timestamp = closest[2]
                self.tooltip.config(text=f"{timestamp}\nLatency: {latency} ms")
                # Place tooltip near mouse
                self.tooltip.place(x=event.guiEvent.x + 10, y=event.guiEvent.y + 10)
            else:
                self.tooltip.place_forget()
        else:
            self.tooltip.place_forget()
    
    def refresh_table_and_chart(self):
        # Update statistics
        total, success, fail, percent_success = fetch_stats()
        self.total_label.config(text=f"Total: {total}")
        self.success_label.config(text=f"Success: {success}")
        self.fail_label.config(text=f"Fail: {fail}")
        self.percent_label.config(text=f"Success %: {percent_success:.2f}%")

        # fetch logs
        no_logs = 20
        latest_logs_for_chart = fetch_latest_logs_for_chart(CART_LIMIT)  # Fetch more for charting
        latest_logs = fetch_latest_logs(LOGS_LIMIT)
        fail_logs = fetch_fail_logs(LOGS_LIMIT)

        # Update recent average ping
        self.rap.config(text="Recent average ping: {:.2f} ms".format(
            sum(latency for _, _, _, latency in latest_logs if latency is not None) / max(1, no_logs)
        ))

        # Update main table
        for row in self.tree.get_children():
            self.tree.delete(row)
        for row in latest_logs:
            tag = "success" if row[2] else "fail"
            self.tree.insert("", tk.END, values=row, tags=(tag,))

        # Update fail table
        for row in self.fail_tree.get_children():
            self.fail_tree.delete(row)
        for row in fail_logs:
            self.fail_tree.insert("", tk.END, values=row, tags=("fail",))

        # Update chart
        chart_data = latest_logs_for_chart
        times = []
        latencies = []
        for t, l in chart_data:
            try:
                dt = datetime.fromisoformat(t)
                times.append(dt)
                latencies.append(l)
            except Exception:
                continue
        self.ax.clear()
        self.ax.set_title("Latency Over Time")
        self.ax.set_xlabel("Time")
        self.ax.set_ylabel("Latency (ms)")
        self.chart_points = []
        if times and latencies:
            self.ax.plot(times, latencies, marker="o", color="blue", linestyle="-")
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            self.ax.tick_params(axis='x', rotation=45)
            # Store points for hover
            self.chart_points = list(zip(times, latencies, [t for t, _ in chart_data]))
        self.fig.tight_layout()
        self.canvas.draw()

        self.after(REFRESH_INTERVAL, self.refresh_table_and_chart)

    def update_intervals(self):
        global PING_INTERVAL, REFRESH_INTERVAL, CART_LIMIT, LOGS_LIMIT
        try:
            ping_val = float(self.ping_interval_var.get())
            refresh_val = int(self.refresh_interval_var.get())
            cart_val = int(self.cart_limit_var.get())
            logs_val = int(self.logs_limit_var.get())
            if ping_val <= 0:
                raise ValueError("PING_INTERVAL must be positive.")
            if refresh_val <= 0:
                raise ValueError("REFRESH_INTERVAL must be positive.")
            if cart_val <= 0:
                raise ValueError("CART_LIMIT must be positive.")
            if logs_val <= 0:
                raise ValueError("LOGS_LIMIT must be positive.")
            PING_INTERVAL = ping_val
            REFRESH_INTERVAL = refresh_val
            CART_LIMIT = cart_val
            LOGS_LIMIT = logs_val
            save_settings_to_db(PING_INTERVAL, REFRESH_INTERVAL, CART_LIMIT, LOGS_LIMIT)
            self.status_label.config(text="Updated!", fg="green")
        except ValueError as ve:
            self.status_label.config(text=f"Invalid input: {ve}", fg="red")
        except Exception as e:
            self.status_label.config(text=f"Error: {e}", fg="red")

    def on_close(self):
            # Properly terminate the app and all threads
            self.destroy()
            import os
            os._exit(0)

async def ping_loop_async():
    loop = asyncio.get_event_loop()
    while True:
        now = datetime.now().isoformat()
        # Run ping in a thread to avoid blocking the event loop
        success, latency = await loop.run_in_executor(None, ping, PING_HOST)
        await loop.run_in_executor(None, log_to_sqlite, now, success, latency)
        # print(f"{now} | Success: {success} | Latency: {latency} ms")
        await asyncio.sleep(PING_INTERVAL)

def start_async_ping_loop():
    asyncio.run(ping_loop_async())

def main():
    # get settings from database or use defaults
    global PING_INTERVAL, REFRESH_INTERVAL, CART_LIMIT, LOGS_LIMIT
    PING_INTERVAL, REFRESH_INTERVAL, CART_LIMIT, LOGS_LIMIT = load_settings_from_db()

    # Start ping loop in a background thread
    t = threading.Thread(target=start_async_ping_loop, daemon=True)
    t.start()
    # Start GUI
    app = PingApp()
    app.mainloop()

if __name__ == "__main__":
    main()