from fastapi import FastAPI, HTTPException, Form, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from dotenv import load_dotenv
from datetime import datetime
from typing import Optional, Dict, Any
from bson import ObjectId
import os
import pandas as pd
import tempfile

load_dotenv()

app = FastAPI(title="Master Contact CRM API")

# ================================
# CORS (Allow your frontend)
# ================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================================
# MongoDB Connection
# ================================
MONGODB_URL = os.getenv("MONGODB_URL")
if not MONGODB_URL:
    raise RuntimeError("MONGODB_URL not set in .env")

client = AsyncIOMotorClient(MONGODB_URL)
db = client[os.getenv("DB_NAME", "CRM")]
contacts_collection = db["crm_data"]          # All contacts go here
config_collection = db["config"]              # For login credentials (optional)

# ================================
# Pydantic Models
# ================================
class LoginRequest(BaseModel):
    email: str
    password: str

# ================================
# Routes
# ================================

# @app.get("/")
# async def root():
#     return {"message": "Master Contact CRM API - Running!"}

# ------------------ Login ------------------
@app.post("/login")
async def login(request: LoginRequest):
    email = request.email.strip().lower()
    password = request.password

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")

    try:
        # Fetch user document from 'users' collection in CRM database
        users_collection = db["users"]
        user_doc = await users_collection.find_one({})
        
        if not user_doc:
            raise HTTPException(status_code=500, detail="User config not found")

        # Get allowed emails and password from the document
        allowed_emails = [e.strip().lower() for e in user_doc.get("allowed_emails", [])]
        db_password = user_doc.get("password", "")

        print(f"DEBUG: Email entered: {email}")
        print(f"DEBUG: Password entered: {password}")
        print(f"DEBUG: Allowed emails: {allowed_emails}")
        print(f"DEBUG: DB Password: {db_password}")

        # Check if email is in allowed list and password matches
        if email in allowed_emails and password == db_password:
            username = email.split("@")[0].replace(".", " ").title()
            return {"status": "success", "message": "Login successful", "user": username}
        else:
            raise HTTPException(status_code=401, detail="Invalid email or password")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Server error")
# ------------------ Submit Contact ------------------
@app.post("/submit")
async def submit_contact(
    company_name: str = Form(...),
    name: str = Form(...),
    designation: str = Form(...),
    mobile: str = Form(...),
    mobile2: Optional[str] = Form(None),
    landline: Optional[str] = Form(None),
    email: str = Form(...),
    email2: Optional[str] = Form(None),
    linkedin: Optional[str] = Form(None),
    address: str = Form(...),
    existing_client: str = Form(...),
    partner_name: Optional[str] = Form(None),

    # NEW FIELDS
    call_date: str = Form(...),
    lead_entry_date: str = Form(...),
    comments: Optional[str] = Form(None),
    disposition: str = Form(...)
):
    try:
        # Convert date strings into proper datetime.date formats
        call_date_parsed = datetime.fromisoformat(call_date)
        lead_entry_date_parsed = datetime.fromisoformat(lead_entry_date)

        contact = {
            "company_name": company_name.strip(),
            "name": name.strip(),
            "designation": designation.strip(),
            "mobile": mobile.strip(),
            "mobile2": mobile2.strip() if mobile2 else None,
            "landline": landline.strip() if landline else None,
            "email": email.strip().lower(),
            "email2": email2.strip().lower() if email2 else None,
            "linkedin": linkedin.strip() if linkedin else None,
            "address": address.strip(),
            "existing_client": existing_client,
            "partner_name": partner_name.strip() if partner_name else None,

            # NEW FIELDS
            "call_date": call_date_parsed,
            "lead_entry_date": lead_entry_date_parsed,
            "comments": comments.strip() if comments else None,
            "disposition": disposition,

            "created_at": datetime.utcnow()
        }

        await contacts_collection.insert_one(contact)
        return {"status": "success", "message": "Contact saved successfully"}

    except Exception as e:
        print("Error saving contact:", e)
        raise HTTPException(status_code=500, detail="Server error while saving contact")

# ------------------ Get History (with filters & pagination) ------------------
@app.get("/get_history")
async def get_history(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    company: str = Query(""),
    phone: str = Query(""),
    disposition: str = Query(""),
    call_start: str = Query(""),
    call_end: str = Query(""),
    lead_start: str = Query(""),
    lead_end: str = Query(""),
    start: str = Query(""),
    end: str = Query("")
):
    query: Dict[str, Any] = {}

    # Global search
    if search.strip():
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"company_name": {"$regex": search, "$options": "i"}},
            {"mobile": {"$regex": search}},
            {"email": {"$regex": search, "$options": "i"}}
        ]

    # Company filter
    if company.strip():
        query["company_name"] = {"$regex": company, "$options": "i"}

    # Phone filter
    if phone.strip():
        query["$or"] = query.get("$or", []) + [
            {"mobile": {"$regex": phone}},
            {"mobile2": {"$regex": phone}}
        ]

    # Disposition filter
    if disposition.strip():
        query["disposition"] = disposition

    # Call date filter
    if call_start and call_end:
        query["call_date"] = {
            "$gte": datetime.fromisoformat(call_start),
            "$lte": datetime.fromisoformat(call_end)
        }

    # Lead entry date filter
    if lead_start and lead_end:
        query["lead_entry_date"] = {
            "$gte": datetime.fromisoformat(lead_start),
            "$lte": datetime.fromisoformat(lead_end)
        }

    # Created_at filter
    if start and end:
        query["created_at"] = {
            "$gte": datetime.fromisoformat(start),
            "$lte": datetime.combine(datetime.fromisoformat(end), datetime.max.time())
        }

    skip = (page - 1) * limit
    cursor = contacts_collection.find(query).sort("created_at", -1).skip(skip).limit(limit)

    history = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        history.append(doc)

    total = await contacts_collection.count_documents(query)
    pages = (total + limit - 1) // limit

    return {
        "history": history,
        "page": page,
        "pages": pages,
        "total": total
    }

# ------------------ Update Contact ------------------
@app.patch("/update/{id}")
async def update_contact(id: str, data: dict = Body(...)):
    if not ObjectId.is_valid(id):
        raise HTTPException(400, detail="Invalid ID")

    # Handle date fields safely
    for field in ["call_date", "lead_entry_date"]:
        if field in data and isinstance(data[field], str):
            data[field] = datetime.fromisoformat(data[field])

    result = await contacts_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": data}
    )

    if result.modified_count == 0:
        raise HTTPException(404, detail="Contact not found or no changes made")

    return {"status": "success", "message": "Contact updated"}

# ------------------ Export to Excel ------------------
@app.get("/export_excel")
async def export_excel():
    try:
        data = []

        # Fetch only valid datetime rows first (sorted)
        cursor_good = contacts_collection.find({
            "created_at": {"$type": "date"}
        }).sort("created_at", -1)

        async for doc in cursor_good:
            data.append(doc)

        # Fetch invalid datetime rows (unsorted)
        cursor_bad = contacts_collection.find({
            "created_at": {"$not": {"$type": "date"}}
        })

        async for doc in cursor_bad:
            data.append(doc)

        # Sanitize documents
        cleaned = []
        for doc in data:
            safe = {}
            for key, value in doc.items():

                if isinstance(value, ObjectId):
                    safe[key] = str(value)

                elif isinstance(value, datetime):
                    safe[key] = value.strftime("%Y-%m-%d %H:%M:%S")

                elif value is None:
                    safe[key] = ""

                elif isinstance(value, (list, dict)):
                    safe[key] = str(value)

                else:
                    safe[key] = value

            cleaned.append(safe)

        df = pd.DataFrame(cleaned)
        
        # Remove created_at column if exists
        if "created_at" in df.columns:
            df = df.drop(columns=["created_at"])

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            
            df.to_excel(tmp.name, index=False)
            file_path = tmp.name

        return FileResponse(
            path=file_path,
            filename=f"Master_Export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        print("EXPORT ERROR:", e)
        raise HTTPException(500, "Excel export failed")


@app.get("/get_contact/{contact_id}")
async def get_contact(contact_id: str):
    if not ObjectId.is_valid(contact_id):
        raise HTTPException(400, "Invalid ID")
    
    contact = await contacts_collection.find_one({"_id": ObjectId(contact_id)})
    if not contact:
        raise HTTPException(404, "Contact not found")
    
    contact["_id"] = str(contact["_id"])
    return contact


# Delete Contact Endpoint
@app.delete("/delete/{contact_id}")
async def delete_contact(contact_id: str):
    try:
        obj_id = ObjectId(contact_id)
        
        # Delete from MongoDB
        result = await contacts_collection.delete_one({"_id": obj_id})
        
        if result.deleted_count == 1:
            return {
                "status": "success",
                "message": "Contact deleted successfully",
                "deleted_count": result.deleted_count
            }
        else:
            raise HTTPException(404, "Contact not found")
            
    except Exception as e:
        raise HTTPException(500, f"Error deleting contact: {str(e)}")

# ================================
# Serve Static Files (HTML + assets)
# MUST BE AT THE VERY END
# ================================

from fastapi.responses import FileResponse
import os

@app.get("/")
async def serve_login():
    file_path = os.path.join("frontend", "login.html")
    if not os.path.exists(file_path):
        raise HTTPException(404, f"File not found: {file_path}")
    return FileResponse(file_path)

@app.get("/dashboard")
async def serve_dashboard():
    file_path = os.path.join("frontend", "index.html")
    if not os.path.exists(file_path):
        raise HTTPException(404, f"File not found: {file_path}")
    return FileResponse(file_path)

# Mount static files BEFORE catch-all routes
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

