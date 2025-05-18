from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from app.auth import decode_access_token
from app.database import get_db_connection
from app.report_generator import generate_business_report
from app.premium import verify_premium_access, verify_premium_or_pass
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import io
import json
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(tags=["Reports"])

class ReportRequest(BaseModel):
    business_name: Optional[str] = None
    owner_name: Optional[str] = None

class ReportTrackingResponse(BaseModel):
    id: int
    user_id: int
    report_type: str
    created_at: str
    report_name: Optional[str] = None

@router.post("/generate")
@router.get("/generate")
async def generate_report(
    request: Optional[ReportRequest] = None, 
    token: str = None, 
    background_tasks: BackgroundTasks = None
):
    """Generate a basic business audit report based on chat history and profession"""
    try:
        # Handle both POST with JSON body and GET with query parameters
        if request is None:
            # For GET requests or POST without body
            request = ReportRequest()
        
        # Get user info and premium status
        user_data = verify_premium_or_pass(token)
        user = user_data[0]
        is_premium = user_data[1]
            
        user_id = user["user_id"]
        
        # Default values if not provided
        business_name = request.business_name or "Your Business"
        owner_name = request.owner_name or "Business Owner"
        
        logger.info(f"Report generation requested for user {user_id}")
        
        # Get the user's profession
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT p.id, p.name 
            FROM user_profession up
            JOIN professions p ON up.profession_id = p.id
            WHERE up.user_id = %s
        """, (user_id,))
        
        profession_result = cursor.fetchone()
        
        if not profession_result:
            cursor.close()
            conn.close()
            raise HTTPException(status_code=400, detail="No profession selected. Please select a profession before generating a report.")
        
        profession_id, profession_name = profession_result
        
        # Get chat history to extract answers
        cursor.execute("""
            SELECT message, response 
            FROM chat_history 
            WHERE user_id = %s 
            ORDER BY timestamp ASC
        """, (user_id,))
        
        chat_history = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if not chat_history:
            raise HTTPException(status_code=400, detail="No chat history found. Please complete the questionnaire before generating a report.")
        
        # Parse the chat history to extract answers
        try:
            answers = extract_answers_from_chat(chat_history, profession_name)
        except Exception as e:
            logger.error(f"Error extracting answers: {str(e)}")
            raise HTTPException(status_code=500, detail="Error processing chat data")
        
        # Record report generation (in background to avoid slowing response)
        if background_tasks:
            report_type = "premium" if is_premium else "basic"
            background_tasks.add_task(
                track_report_generation, 
                user_id=user_id, 
                report_type=report_type,
                report_name=f"{business_name} Audit Report"
            )
        
        # Generate the PDF report
        try:
            pdf_data = generate_business_report(user_id, business_name, owner_name, profession_name, answers)
        except Exception as e:
            logger.error(f"Error generating report: {str(e)}")
            raise HTTPException(status_code=500, detail="Error generating report")
        
        # Return the PDF as a downloadable file
        filename = f"{business_name.replace(' ', '_')}_Audit_Report.pdf"
        
        return StreamingResponse(
            io.BytesIO(pdf_data),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        logger.error(f"Report generation error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating report: {str(e)}")

@router.post("/premium-report")
async def generate_premium_report(
    request: ReportRequest, 
    background_tasks: BackgroundTasks,
    user = Depends(verify_premium_access)
):
    """Generate a premium business audit report with enhanced features (premium users only)"""
    user_id = user["user_id"]
    
    # Default values if not provided
    business_name = request.business_name or "Your Business"
    owner_name = request.owner_name or "Business Owner"
    
    logger.info(f"Premium report generation requested for user {user_id}")
    
    # Get the user's profession
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT p.id, p.name 
        FROM user_profession up
        JOIN professions p ON up.profession_id = p.id
        WHERE up.user_id = %s
    """, (user_id,))
    
    profession_result = cursor.fetchone()
    
    if not profession_result:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="No profession selected. Please select a profession before generating a report.")
    
    profession_id, profession_name = profession_result
    
    # Get chat history to extract answers
    cursor.execute("""
        SELECT message, response 
        FROM chat_history 
        WHERE user_id = %s 
        ORDER BY timestamp ASC
    """, (user_id,))
    
    chat_history = cursor.fetchall()
    cursor.close()
    conn.close()
    
    if not chat_history:
        raise HTTPException(status_code=400, detail="No chat history found. Please complete the questionnaire before generating a report.")
    
    # Parse the chat history to extract answers
    try:
        answers = extract_answers_from_chat(chat_history, profession_name)
    except Exception as e:
        logger.error(f"Error extracting answers: {str(e)}")
        raise HTTPException(status_code=500, detail="Error processing chat data")
    
    # Record premium report generation
    background_tasks.add_task(
        track_report_generation, 
        user_id=user_id, 
        report_type="premium-enhanced",
        report_name=f"{business_name} Premium Audit Report"
    )
    
    # Generate the premium PDF report with enhanced features
    try:
        # Note: In a real implementation, you might have a different generator for premium reports
        # with additional features or enhanced content
        pdf_data = generate_business_report(user_id, business_name, owner_name, profession_name, answers)
    except Exception as e:
        logger.error(f"Error generating premium report: {str(e)}")
        raise HTTPException(status_code=500, detail="Error generating premium report")
    
    # Return the PDF as a downloadable file
    filename = f"{business_name.replace(' ', '_')}_Premium_Audit_Report.pdf"
    
    return StreamingResponse(
        io.BytesIO(pdf_data),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/report-history", response_model=List[ReportTrackingResponse])
async def get_user_report_history(user = Depends(verify_premium_access)):
    """Get history of generated reports (premium users only)"""
    user_id = user["user_id"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, user_id, report_type, created_at, report_name
        FROM report_tracking
        WHERE user_id = %s
        ORDER BY created_at DESC
    """, (user_id,))
    
    reports = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    result = []
    for report in reports:
        created_at = report[3].isoformat() if hasattr(report[3], 'isoformat') else str(report[3])
        
        result.append({
            "id": report[0],
            "user_id": report[1],
            "report_type": report[2],
            "created_at": created_at,
            "report_name": report[4]
        })
    
    return result

# Helper function to track report generation
def track_report_generation(user_id: int, report_type: str, report_name: str = None):
    """Record report generation in database for tracking"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # First, check if report_tracking table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'report_tracking'
            )
        """)
        
        table_exists = cursor.fetchone()[0]
        
        # Create table if it doesn't exist
        # if not table_exists:
        #     cursor.execute("""
        #         CREATE TABLE report_tracking (
        #             id SERIAL PRIMARY KEY,
        #             user_id INT REFERENCES users(id) ON DELETE CASCADE,
        #             report_type VARCHAR(50) NOT NULL,
        #             report_name TEXT,
        #             created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        #         )
        #     """)
        
        # Insert record
        cursor.execute("""
            INSERT INTO report_tracking (user_id, report_type, report_name)
            VALUES (%s, %s, %s)
        """, (user_id, report_type, report_name))
        
        conn.commit()
        
        cursor.close()
        conn.close()
        
        logger.info(f"Tracked {report_type} report generation for user {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error tracking report generation: {str(e)}")
        return False

def extract_answers_from_chat(chat_history, profession_name):
    """Extract structured answers from chat history"""
    # Initialize the sections based on the profession
    sections = initialize_sections_for_profession(profession_name)
    
    # Try to extract business name and owner name first
    business_name, owner_name = extract_business_info_from_chat(chat_history)
    
    if business_name:
        # Add business name to the first section
        for section in sections:
            if section["title"] == "Business Basics":
                section["answers"]["_business_name"] = business_name
                break
    
    if owner_name:
        # Add owner name to the first section
        for section in sections:
            if section["title"] == "Business Basics":
                section["answers"]["_owner_name"] = owner_name
                break
    
    current_section = None
    current_question = None
    
    # Process each message-response pair
    for message, response in chat_history:
        # Skip empty messages
        if not message or not response:
            continue
            
        # Look for section titles and questions in the responses
        for section in sections:
            section_title = section["title"]
            
            # If the bot mentions a section title, set it as the current section
            if section_title.lower() in response.lower():
                current_section = section_title
                
            # Check for questions from this section in the response
            for question in section["questions"]:
                # Clean up the question for matching (remove special characters)
                clean_question = ' '.join(question.lower().replace('?', '').replace('(', '').replace(')', '').split())
                clean_response = response.lower()
                
                # If the question is mentioned in the response
                if clean_question in clean_response:
                    current_question = question
                    
                    # Look for the user's answer in the next message
                    if message and current_section and current_question:
                        # Find the section in our data structure
                        for s in sections:
                            if s["title"] == current_section:
                                # Add the answer
                                s["answers"][current_question] = message
                                break
    
    # Process for questions where only part of the question is in the response
    # This is a more flexible approach for matching questions
    for message, response in chat_history:
        if not message or not response:
            continue
            
        for section in sections:
            for question in section["questions"]:
                # Skip questions that already have answers
                if question in section["answers"]:
                    continue
                    
                # Get key words from the question (words with 5+ characters are likely significant)
                keywords = [word for word in question.lower().split() if len(word) >= 5]
                
                # Count how many keywords appear in the response
                keyword_matches = sum(1 for keyword in keywords if keyword in response.lower())
                
                # If most of the keywords match, it's likely this question
                if keywords and keyword_matches / len(keywords) >= 0.5:
                    section["answers"][question] = message
    
    # For any remaining unanswered questions, try to find answers based on context
    # This is a simplified approach and could be enhanced further
    for section in sections:
        for question in section["questions"]:
            if question not in section["answers"]:
                # Look for answers where the question wasn't explicitly mentioned
                for message, response in chat_history:
                    if not message or not response:
                        continue
                        
                    # Get key words from the question
                    keywords = [word for word in question.lower().split() if len(word) >= 5]
                    
                    # Check if the response mentions most keywords and the message is an answer
                    response_has_keywords = sum(1 for keyword in keywords if keyword in response.lower())
                    if keywords and response_has_keywords / len(keywords) >= 0.3 and len(message) > 3:
                        section["answers"][question] = message
                        break
    
    # Return the sections with their answers
    return sections

def initialize_sections_for_profession(profession_name):
    """Initialize the sections structure based on profession"""
    # This is a simplified implementation - in a production system, this would be more dynamic
    # and could fetch the structure from your profession_prompts table
    
    if "fitness" in profession_name.lower():
        return [
            {
                "title": "Business Basics",
                "questions": [
                    "What is the name of your fitness business?",
                    "What type of fitness business do you operate?",
                    "Where is it located?",
                    "How long have you been in business?",
                    "Do you have a website or social media pages?",
                    "How many staff or trainers do you currently employ?"
                ],
                "answers": {}
            },
            {
                "title": "Revenue & Membership Metrics",
                "questions": [
                    "What is your average monthly revenue?",
                    "How many active members/clients do you currently have?",
                    "What are your primary revenue streams?",
                    "What is your average customer lifetime value?",
                    "What is your customer acquisition cost?",
                    "What is your monthly member/client retention rate?"
                ],
                "answers": {}
            },
            {
                "title": "Operational Challenges",
                "questions": [
                    "How do you currently handle class bookings or appointments?",
                    "What are your busiest hours/days?",
                    "How do you manage equipment maintenance and facility upkeep?",
                    "What are the biggest operational bottlenecks you face?",
                    "How do you handle member onboarding and support?"
                ],
                "answers": {}
            },
            {
                "title": "Client Behavior & Loyalty",
                "questions": [
                    "How often does your average client visit per week?",
                    "Do you track client progress? If yes, how?",
                    "What retention strategies do you currently employ?",
                    "Do you have a referral program? If yes, how effective is it?",
                    "What feedback mechanisms do you have in place?"
                ],
                "answers": {}
            },
            {
                "title": "Competitor & Market Awareness",
                "questions": [
                    "Who are your top 3 competitors in your area?",
                    "What makes your fitness business unique or better?",
                    "How would you describe your pricing compared to competitors?",
                    "What fitness trends have you observed in your market?",
                    "How do you keep up with industry developments?"
                ],
                "answers": {}
            },
            {
                "title": "Tech & Automation",
                "questions": [
                    "What systems/tools do you use for member management?",
                    "What systems/tools do you use for scheduling and bookings?",
                    "What systems/tools do you use for marketing?",
                    "Are you using any fitness tracking or progress monitoring technology?",
                    "Are you open to implementing more technology to improve operations?"
                ],
                "answers": {}
            }
        ]
    
    elif "restaurant" in profession_name.lower():
        return [
            {
                "title": "Business Basics",
                "questions": [
                    "What is the name of your restaurant?",
                    "Where is it located?",
                    "Do you have a website or social media pages?",
                    "How many staff members do you currently have?"
                ],
                "answers": {}
            },
            {
                "title": "Revenue & Operational Metrics",
                "questions": [
                    "What is your average monthly revenue?",
                    "What is your table turnover rate per night?",
                    "What is your Customer Acquisition Cost?",
                    "What % of your staff time is spent on guest-facing activities?"
                ],
                "answers": {}
            },
            {
                "title": "Operational Challenges",
                "questions": [
                    "How do you currently handle reservations?",
                    "Approximately how many hours per week are spent on reservation handling?",
                    "Approximately how many hours per week are spent on guest communications?",
                    "Approximately how many hours per week are spent on social media or review management?",
                    "What are the biggest operational bottlenecks you face?"
                ],
                "answers": {}
            },
            {
                "title": "Guest Behavior & Loyalty",
                "questions": [
                    "Do you segment your customers?",
                    "How often do guests return after a visit?",
                    "Do you track guest preferences?",
                    "Are you using any loyalty program or guest personalization tactics?"
                ],
                "answers": {}
            },
            {
                "title": "Competitor & Market Awareness",
                "questions": [
                    "Who are your top 3 competitors nearby?",
                    "What makes your restaurant different or better?",
                    "Do you consider your pricing premium, average, or budget?",
                    "How is your online review score and general sentiment?"
                ],
                "answers": {}
            },
            {
                "title": "Tech & Automation",
                "questions": [
                    "What systems/tools are you using for reservation management?",
                    "What systems/tools are you using for POS?",
                    "What systems/tools are you using for marketing or loyalty tracking?",
                    "Are these systems integrated? Any pain points?",
                    "Are you open to using AI/automation to improve operations?"
                ],
                "answers": {}
            }
        ]
    
    # More professions omitted for brevity, same as original code
    
    return [
        {
            "title": "Business Basics",
            "questions": [
                "What is the name of your business?",
                "Where is it located?",
                "How long have you been in business?",
                "How many staff members do you currently have?"
            ],
            "answers": {}
        },
        {
            "title": "Revenue & Operational Metrics",
            "questions": [
                "What is your average monthly revenue?",
                "Who is your target audience?",
                "What is your Customer Acquisition Cost?",
                "What are your biggest operational costs?"
            ],
            "answers": {}
        },
        {
            "title": "Operational Challenges",
            "questions": [
                "What are your main daily operations?",
                "What processes take up most of your time?",
                "What are the biggest operational bottlenecks you face?",
                "How do you currently handle customer communications?"
            ],
            "answers": {}
        },
        {
            "title": "Customer Behavior & Loyalty",
            "questions": [
                "Do you segment your customers?",
                "What is your customer retention rate?",
                "Do you have any loyalty program?",
                "How do you gather customer feedback?"
            ],
            "answers": {}
        },
        {
            "title": "Competitor & Market Awareness",
            "questions": [
                "Who are your top 3 competitors?",
                "What makes your business different or better?",
                "Do you consider your pricing premium, average, or budget?",
                "What market trends are affecting your business?"
            ],
            "answers": {}
        },
        {
            "title": "Tech & Automation",
            "questions": [
                "What software or tools do you currently use in your business?",
                "Are these systems integrated? Any pain points?",
                "What processes do you wish were more automated?",
                "Are you open to using AI/automation to improve operations?"
            ],
            "answers": {}
        }
    ]

def extract_business_info_from_chat(chat_history):
    """Extract basic business info from chat history"""
    business_name = None
    owner_name = None
    
    # Look for business name in the chat
    for message, response in chat_history:
        if ("name of your" in response.lower() and "business" in response.lower()) or \
           ("name of your" in response.lower() and "restaurant" in response.lower()) or \
           ("name of your" in response.lower() and "fitness" in response.lower()):
            business_name = message
            break
    
    return business_name, owner_name