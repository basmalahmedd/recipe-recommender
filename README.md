# 📖 Recipe Recommender (FastAPI + React)

This project is a simple recipe recommendation app.  
It has two parts:  
- **Backend**: FastAPI (Python)  
- **Frontend**: React (JavaScript)  

---

## ⚙️ Backend (FastAPI)

1. **Go inside the project root (where `main.py` is):**
   ```bash
   cd uploadreay
   ```

2. **Create virtual environment (only once):**
   ```bash
   python -m venv venv
   ```

3. **Activate virtual environment:**
   - On **Windows (PowerShell)**:
     ```bash
     venv\Scripts\activate
     ```
   - On **Linux/Mac**:
     ```bash
     source venv/bin/activate
     ```

4. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

5. **Run FastAPI server:**
   ```bash
   uvicorn main:app --reload
   ```
   Server will run at 👉 `http://127.0.0.1:8000`

---

## 💻 Frontend (React)

1. **Go into `ui/` folder:**
   ```bash
   cd ui
   ```

2. **Install dependencies (only once):**
   ```bash
   npm install
   ```

3. **Run React app:**
   ```bash
   npm start
   ```
   App will run at 👉 `http://localhost:3000`

---

## 🌐 Usage

1. Make sure **backend** is running (`http://127.0.0.1:8000`).  
2. Open React app (`http://localhost:3000`).  
3. Enter ingredients (comma separated) → click **Get Recipes**.  
4. Recommended recipes will appear.

---
