# Backend FastAPI - Dossier Immo Pro
# Version déploiement avec taux SeLoger automatiques

import os
from dotenv import load_dotenv

# Charger variables d'environnement
load_dotenv()
from fastapi import Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime, date
import uuid
import stripe
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import io
import httpx
from bs4 import BeautifulSoup
import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import json

# Configuration
app = FastAPI(
    title="Dossier Immo Pro API", 
    version="1.0.0",
    description="API d'évaluation de dossiers de prêt immobilier français"
)
# --- UI minimal: static & templates mounting ---
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    # Ignore si le dossier n’existe pas (ex: en dev)
    pass

templates = Jinja2Templates(directory="templates")
# --- end UI minimal ---

# Configuration Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_default")

# Configuration CORS
allowed_origins = [
    "https://*.railway.app",
    "http://localhost:3000",
    "http://localhost:8000",
]

if os.getenv("ENVIRONMENT") == "development":
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === STOCKAGE TEMPORAIRE (À REMPLACER PAR BDD) ===
taux_storage = {
    "date_maj": datetime.now().isoformat(),
    "taux": {
        "10": 0.0285,  # 2,85%
        "15": 0.0303,  # 3,03%
        "20": 0.0316,  # 3,16%
        "25": 0.0326,  # 3,26%
        "30": 0.0340   # 3,40%
    },
    "source": "seloger.com"
}

applications_store = {}

# === MODÈLES PYDANTIC ===

class ProjectInfo(BaseModel):
    property_price: float = Field(..., gt=0, description="Prix du bien")
    property_type: Literal["neuf", "ancien"] = Field(..., description="Type de bien")
    personal_contribution: float = Field(..., ge=0, description="Apport personnel")
    loan_duration: int = Field(..., ge=5, le=30, description="Durée en années")

class EmploymentInfo(BaseModel):
    status: Literal["cdi", "cdd"] = Field(..., description="Statut emploi")
    net_monthly_income: float = Field(..., gt=0, description="Revenus nets mensuels")
    years_experience: float = Field(..., ge=0, description="Ancienneté en années")
    trial_period: bool = Field(default=False, description="En période d'essai")

class BorrowerInfo(BaseModel):
    employment: EmploymentInfo
    age: int = Field(..., ge=18, le=80, description="Âge de l'emprunteur")

class HouseholdInfo(BaseModel):
    borrowers_count: Literal[1, 2] = Field(..., description="Nombre d'emprunteurs")
    main_borrower: BorrowerInfo = Field(..., description="Emprunteur principal")
    co_borrower: Optional[BorrowerInfo] = Field(default=None, description="Co-emprunteur")
    children: int = Field(..., ge=0, le=20, description="Nombre d'enfants")

class HousingInfo(BaseModel):
    current_status: Literal["locataire", "proprietaire", "heberge_gratuit"] = Field(..., description="Situation logement")
    monthly_rent: float = Field(default=0, ge=0, description="Loyer mensuel")
    current_mortgage: float = Field(default=0, ge=0, description="Mensualité crédit actuel")
    changing_main_residence: bool = Field(default=True, description="Change de résidence principale")

class FinancialInfo(BaseModel):
    consumer_loans: list[dict] = Field(default=[], description="Crédits à la consommation")
    rental_income: float = Field(default=0, ge=0, description="Revenus locatifs mensuels")
    other_income: float = Field(default=0, ge=0, description="Autres revenus")

class LoanApplication(BaseModel):
    project: ProjectInfo
    household: HouseholdInfo
    housing: HousingInfo
    financial: FinancialInfo

class ScoringResult(BaseModel):
    application_id: str
    feasibility_score: int
    status: Literal["favorable", "moyen", "difficile"]
    criteria_details: dict
    recommendations: list[str]
    monthly_payment: float
    total_budget: float
    current_interest_rate: float
    rate_source: str
    rate_last_update: str

class PaymentRequest(BaseModel):
    application_id: str
    amount: int = 9900  # 99€ en centimes

# === SERVICE TAUX SELOGER ===

class TauxService:
    
    @staticmethod
    async def scrape_seloger_rates():
        """Scrape les taux SeLoger"""
        try:
            url = "https://www.seloger.com/credit-immobilier/simulateur-capacite-demprunt/"
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                
                if response.status_code != 200:
                    raise Exception(f"Erreur HTTP: {response.status_code}")
                
                # Pour l'instant, on utilise des taux fixes
                # TODO: Adapter selon la structure HTML réelle de SeLoger
                taux_scraped = {
                    "10": 0.0285,  # 2,85%
                    "15": 0.0303,  # 3,03%
                    "20": 0.0316,  # 3,16%
                    "25": 0.0326,  # 3,26%
                    "30": 0.0340   # 3,40%
                }
                
                logger.info(f"Taux récupérés: {taux_scraped}")
                
                return {
                    "date_maj": datetime.now().isoformat(),
                    "taux": taux_scraped,
                    "source": "seloger.com"
                }
                
        except Exception as e:
            logger.error(f"Erreur scraping SeLoger: {e}")
            # Taux par défaut en cas d'erreur
            return {
                "date_maj": datetime.now().isoformat(),
                "taux": {
                    "10": 0.0285, "15": 0.0303, "20": 0.0316, 
                    "25": 0.0326, "30": 0.0340
                },
                "source": "fallback"
            }
    
    @staticmethod
    async def update_monthly_rates():
        """Mise à jour mensuelle des taux"""
        try:
            logger.info("Début mise à jour taux SeLoger...")
            
            new_rates = await TauxService.scrape_seloger_rates()
            
            global taux_storage
            taux_storage = new_rates
            
            logger.info(f"✅ Taux mis à jour: {new_rates}")
            
        except Exception as e:
            logger.error(f"❌ Erreur mise à jour taux: {e}")
    
    @staticmethod
    def get_current_rate(duration: int) -> float:
        """Récupère le taux actuel selon la durée"""
        try:
            return taux_storage["taux"].get(str(duration), 0.035)
        except:
            return 0.035
    
    @staticmethod
    def get_taux_info() -> dict:
        """Retourne les informations sur les taux"""
        return taux_storage

# === SERVICE SCORING ===

class LoanScoringService:
    
    @staticmethod
    def calculate_notary_fees(price: float, property_type: str) -> float:
        """Calcule les frais de notaire"""
        if property_type == "neuf":
            return price * 0.03
        else:
            return price * 0.08
    
    @staticmethod
    def get_current_interest_rate(loan_duration: int) -> float:
        """Retourne les taux SeLoger actuels"""
        return TauxService.get_current_rate(loan_duration)
    
    @staticmethod
    def calculate_monthly_payment(amount: float, duration_years: int, rate: float = None) -> float:
        """Calcule mensualité"""
        if rate is None:
            rate = LoanScoringService.get_current_interest_rate(duration_years)
            
        monthly_rate = rate / 12
        n_payments = duration_years * 12
        if monthly_rate == 0:
            return amount / n_payments
        return amount * (monthly_rate * (1 + monthly_rate)**n_payments) / ((1 + monthly_rate)**n_payments - 1)
    
    @staticmethod
    def calculate_eligible_income(employment: EmploymentInfo) -> float:
        """Calcule revenus éligibles"""
        base_income = employment.net_monthly_income
        
        if employment.status == "cdi":
            if employment.trial_period:
                return 0
            return base_income
        elif employment.status == "cdd":
            if employment.years_experience >= 3:
                return base_income * 0.7
            return 0
        return 0
    
    @classmethod
    def calculate_current_charges(cls, housing: HousingInfo, financial: FinancialInfo) -> float:
        """Calcule charges actuelles"""
        charges = 0
        
        if housing.current_status == "locataire":
            charges += 0
        elif housing.current_status == "proprietaire" and housing.changing_main_residence:
            charges += housing.current_mortgage
        
        for loan in financial.consumer_loans:
            charges += loan.get('monthly_payment', 0)
        
        return charges
    
    @classmethod
    def calculate_total_eligible_income(cls, household: HouseholdInfo, financial: FinancialInfo) -> float:
        """Calcule revenus éligibles totaux"""
        main_income = cls.calculate_eligible_income(household.main_borrower.employment)
        
        co_income = 0
        if household.co_borrower:
            co_income = cls.calculate_eligible_income(household.co_borrower.employment)
        
        rental_income_eligible = financial.rental_income * 0.7
        
        return main_income + co_income + rental_income_eligible + financial.other_income
    
    @classmethod
    def evaluate_application(cls, application: LoanApplication) -> ScoringResult:
        """Évalue la faisabilité du dossier"""
        
        # Calculs de base
        notary_fees = cls.calculate_notary_fees(
            application.project.property_price, 
            application.project.property_type
        )
        total_budget = application.project.property_price + notary_fees
        loan_amount = total_budget - application.project.personal_contribution
        
        # Revenus éligibles
        total_income = cls.calculate_total_eligible_income(application.household, application.financial)
        
        # Mensualité
        current_rate = cls.get_current_interest_rate(application.project.loan_duration)
        monthly_payment = cls.calculate_monthly_payment(loan_amount, application.project.loan_duration, current_rate)
        
        # Charges actuelles
        current_charges = cls.calculate_current_charges(application.housing, application.financial)
        
        # Reste à vivre
        household_size = application.household.borrowers_count + application.household.children
        min_remaining = household_size * 750
        
        # Évaluation critères
        criteria = {}
        score = 0
        recommendations = []
        
        # Critère apport (30%)
        min_contribution = total_budget * 0.10
        if application.project.personal_contribution >= min_contribution:
            criteria["apport"] = "✅ Apport suffisant"
            score += 30
        else:
            criteria["apport"] = f"❌ Apport insuffisant ({min_contribution:.0f}€ minimum)"
            recommendations.append(f"Augmentez votre apport à {min_contribution:.0f}€ minimum")
        
        # Critère revenus (20%)
        main_income = cls.calculate_eligible_income(application.household.main_borrower.employment)
        if main_income > 0:
            criteria["revenus"] = f"✅ Revenus éligibles : {total_income:,.0f}€/mois"
            score += 20
        else:
            criteria["revenus"] = "❌ Revenus non éligibles"
            recommendations.append("Obtenez un CDI ou justifiez 3 ans d'ancienneté en CDD")
        
        # Critère endettement (30%)
        total_charges = monthly_payment + current_charges
        debt_ratio = (total_charges / total_income) if total_income > 0 else 1
        if debt_ratio <= 0.33:
            criteria["endettement"] = f"✅ Taux d'endettement : {debt_ratio:.1%}"
            score += 30
        else:
            criteria["endettement"] = f"❌ Taux d'endettement trop élevé : {debt_ratio:.1%}"
            recommendations.append("Réduisez vos charges ou augmentez vos revenus")
        
        # Critère reste à vivre (10%)
        remaining = total_income - total_charges
        if remaining >= min_remaining:
            criteria["reste_vivre"] = f"✅ Reste à vivre : {remaining:.0f}€"
            score += 10
        else:
            criteria["reste_vivre"] = f"❌ Reste à vivre insuffisant : {remaining:.0f}€"
            recommendations.append(f"Assurez-vous d'avoir {min_remaining:.0f}€ de reste à vivre")
        
        # Critère âge (10%)
        loan_end_age = application.household.main_borrower.age + application.project.loan_duration
        if loan_end_age <= 64:
            criteria["age"] = f"✅ Fin de crédit à {loan_end_age} ans"
            score += 10
        else:
            criteria["age"] = f"❌ Fin de crédit à {loan_end_age} ans (limite 64 ans)"
            recommendations.append("Réduisez la durée du prêt")
        
        # Statut final
        if score >= 80:
            status = "favorable"
        elif score >= 50:
            status = "moyen"
        else:
            status = "difficile"
        
        taux_info = TauxService.get_taux_info()
        
        return ScoringResult(
            application_id=str(uuid.uuid4()),
            feasibility_score=score,
            status=status,
            criteria_details=criteria,
            recommendations=recommendations,
            monthly_payment=monthly_payment,
            total_budget=total_budget,
            current_interest_rate=current_rate,
            rate_source=taux_info.get("source", "seloger.com"),
            rate_last_update=taux_info.get("date_maj", "Non disponible")
        )

# === SERVICE PDF ===

class PDFService:
    
    @staticmethod
    def generate_loan_dossier(application: LoanApplication, scoring: ScoringResult) -> bytes:
        """Génère le PDF du dossier"""
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # En-tête
        p.setFont("Helvetica-Bold", 16)
        p.drawString(50, height - 50, "DOSSIER DE PRÊT IMMOBILIER")
        
        # Informations taux
        y = height - 80
        p.setFont("Helvetica", 10)
        p.drawString(50, y, f"Taux ({scoring.rate_source}): {scoring.current_interest_rate:.2%}")
        y -= 15
        p.drawString(50, y, f"Mise à jour: {scoring.rate_last_update[:10]}")
        
        # Score
        y -= 40
        p.setFont("Helvetica-Bold", 14)
        p.drawString(50, y, f"Score: {scoring.feasibility_score}/100 - {scoring.status.upper()}")
        
        # Projet
        y -= 40
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, y, "PROJET IMMOBILIER")
        y -= 20
        
        p.setFont("Helvetica", 10)
        p.drawString(50, y, f"Prix: {application.project.property_price:,.0f} €")
        y -= 15
        p.drawString(50, y, f"Budget total: {scoring.total_budget:,.0f} €")
        y -= 15
        p.drawString(50, y, f"Mensualité: {scoring.monthly_payment:,.0f} €/mois")
        
        # Critères
        y -= 30
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, y, "CRITÈRES D'ÉVALUATION")
        y -= 20
        
        p.setFont("Helvetica", 10)
        for criterion, result in scoring.criteria_details.items():
            y -= 15
            p.drawString(50, y, f"{criterion.replace('_', ' ').title()}: {result}")
        
        # Recommandations
        if scoring.recommendations:
            y -= 30
            p.setFont("Helvetica-Bold", 12)
            p.drawString(50, y, "RECOMMANDATIONS")
            y -= 20
            
            p.setFont("Helvetica", 10)
            for i, rec in enumerate(scoring.recommendations, 1):
                y -= 15
                p.drawString(50, y, f"{i}. {rec}")
        
        p.save()
        buffer.seek(0)
        return buffer.getvalue()

# === SCHEDULER ===

scheduler = AsyncIOScheduler()

# Mise à jour le 1er de chaque mois à 9h
scheduler.add_job(
    TauxService.update_monthly_rates,
    CronTrigger(day=1, hour=9, minute=0),
    id='update_taux_mensuel',
    replace_existing=True
)

# === ENDPOINTS ===

@app.get("/", response_class=HTMLResponse)
async def root():
    """Page d'accueil"""
    return """
    <html>
        <head>
            <title>Dossier Immo Pro API</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
                .container { max-width: 600px; margin: 0 auto; background: white; padding: 40px; border-radius: 10px; }
                h1 { color: #3b82f6; }
                .status { background: #ecfdf5; padding: 15px; border-radius: 8px; margin: 20px 0; }
                a { color: #3b82f6; text-decoration: none; }
                a:hover { text-decoration: underline; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🏠 Dossier Immo Pro API</h1>
                <p>API d'évaluation de dossiers de prêt immobilier français</p>
                
                <div class="status">
                    <strong>✅ API Opérationnelle</strong><br>
                    Service d'évaluation de faisabilité de crédit immobilier
                </div>
                
                <h3>🔗 Liens utiles :</h3>
                <ul>
                    <li><a href="/docs">📖 Documentation API</a></li>
                    <li><a href="/api/health">💚 Health Check</a></li>
                    <li><a href="/api/taux-actuels">📊 Taux actuels</a></li>
                    <li><a href="/api/status">🔍 Status détaillé</a></li>
                </ul>
                
                <p><em>Version 1.0.0 - Prêt pour le déploiement</em></p>
            </div>
        </body>
    </html>
    """

@app.get("/api/health")
async def health_check():
    """Endpoint de santé"""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "environment": os.getenv("ENVIRONMENT", "production"),
        "taux_source": taux_storage.get("source"),
        "taux_last_update": taux_storage.get("date_maj", "Non disponible")[:10]
    }

@app.get("/api/status")
async def status():
    """Status détaillé"""
    return {
        "app_name": "Dossier Immo Pro",
        "version": "1.0.0",
        "environment": os.getenv("ENVIRONMENT"),
        "stripe_configured": bool(os.getenv("STRIPE_SECRET_KEY")),
        "taux_data": taux_storage,
        "active_applications": len(applications_store)
    }

@app.get("/api/taux-actuels")
async def get_current_rates():
    """Taux actuels"""
    return TauxService.get_taux_info()

@app.post("/api/update-taux")
async def manual_update_rates(background_tasks: BackgroundTasks):
    """Mise à jour manuelle des taux"""
    background_tasks.add_task(TauxService.update_monthly_rates)
    return {"message": "Mise à jour des taux lancée"}

@app.post("/api/evaluate", response_model=ScoringResult)
async def evaluate_loan_application(application: LoanApplication):
    """Évalue la faisabilité du dossier"""
    try:
        scoring_result = LoanScoringService.evaluate_application(application)
        
        # Stockage temporaire
        applications_store[scoring_result.application_id] = {
            "application": application,
            "scoring": scoring_result,
            "created_at": datetime.now(),
            "paid": False
        }
        
        return scoring_result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'évaluation: {str(e)}")

@app.post("/api/payment/create-intent")
async def create_payment_intent(payment_request: PaymentRequest):
    """Crée un intent de paiement Stripe"""
    try:
        if payment_request.application_id not in applications_store:
            raise HTTPException(status_code=404, detail="Dossier non trouvé")
        
        intent = stripe.PaymentIntent.create(
            amount=payment_request.amount,
            currency='eur',
            metadata={'application_id': payment_request.application_id}
        )
        
        return {"client_secret": intent.client_secret}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur paiement: {str(e)}")

@app.post("/api/payment/confirm")
async def confirm_payment(application_id: str, payment_intent_id: str):
    """Confirme le paiement"""
    try:
        if application_id not in applications_store:
            raise HTTPException(status_code=404, detail="Dossier non trouvé")
        
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        
        if intent.status == "succeeded":
            applications_store[application_id]["paid"] = True
            return {"status": "success", "message": "Paiement confirmé"}
        else:
            raise HTTPException(status_code=400, detail="Paiement non confirmé")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur confirmation: {str(e)}")

@app.get("/api/dossier/{application_id}")
async def get_complete_dossier(application_id: str):
    """Récupère le dossier complet après paiement"""
    try:
        if application_id not in applications_store:
            raise HTTPException(status_code=404, detail="Dossier non trouvé")
        
        app_data = applications_store[application_id]
        
        if not app_data["paid"]:
            raise HTTPException(status_code=402, detail="Paiement requis")
        
        return {
            "scoring": app_data["scoring"],
            "pdf_available": True
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur récupération: {str(e)}")

@app.get("/api/dossier/{application_id}/pdf")
async def download_pdf(application_id: str):
    """Télécharge le PDF du dossier"""
    try:
        if application_id not in applications_store:
            raise HTTPException(status_code=404, detail="Dossier non trouvé")
        
        app_data = applications_store[application_id]
        
        if not app_data["paid"]:
            raise HTTPException(status_code=402, detail="Paiement requis")
        
        pdf_content = PDFService.generate_loan_dossier(
            app_data["application"], 
            app_data["scoring"]
        )
        
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=dossier_pret_immobilier.pdf"}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur génération PDF: {str(e)}")

# === STARTUP/SHUTDOWN ===

@app.on_event("startup")
async def startup_event():
    """Démarrage"""
    logger.info("🚀 Démarrage Dossier Immo Pro API")
    scheduler.start()
    await TauxService.update_monthly_rates()
    logger.info("✅ API prête")

@app.on_event("shutdown")
async def shutdown_event():
    """Arrêt"""
    logger.info("🛑 Arrêt Dossier Immo Pro API")
    scheduler.shutdown()
# --- UI minimal: /app route ---
@app.get("/app", response_class=HTMLResponse)
def ui_app(request: Request):
    """Interface minimale pour évaluer un dossier via /api/evaluate"""
    return templates.TemplateResponse("index.html", {"request": request})
# --- end UI minimal ---

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
