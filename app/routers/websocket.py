from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from app.chatbot import get_chat_history, process_chat, get_user_profession, has_completed_all_questions, stream_chat
from app.auth import decode_access_token
from app.database import get_db_connection_context
import json
import asyncio
from datetime import datetime
import logging
from concurrent.futures import ThreadPoolExecutor
import weakref

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat Websocket"])

# Keep track of active connections for monitoring
active_connections = weakref.WeakSet()

# Thread pool for database operations
db_executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="websocket_db")

async def get_user_data_async(user_id):
    """Get user data asynchronously"""
    loop = asyncio.get_event_loop()
    
    def get_user_data():
        try:
            with get_db_connection_context() as conn:
                with conn.cursor() as cursor:
                    # Check if user is suspended
                    cursor.execute("SELECT status FROM users WHERE id = %s", (user_id,))
                    status_result = cursor.fetchone()
                    
                    if not status_result:
                        return {"error": "User not found"}
                    
                    if status_result[0] == "suspended":
                        return {"error": "Account suspended"}
                    
                    # Check if user has a profession set
                    cursor.execute("""
                        SELECT p.name 
                        FROM user_profession up
                        JOIN professions p ON up.profession_id = p.id
                        WHERE up.user_id = %s
                    """, (user_id,))
                    
                    profession_result = cursor.fetchone()
                    
                    if not profession_result:
                        return {"error": "No profession set"}
                    
                    return {
                        "status": "active",
                        "profession_name": profession_result[0]
                    }
        except Exception as e:
            logger.error(f"Error getting user data: {e}")
            return {"error": str(e)}
    
    return await loop.run_in_executor(db_executor, get_user_data)

@router.websocket("/home-chat")
async def home_websocket_endpoint(websocket: WebSocket):
    """WebSocket handler for home page demo chat - optimized for concurrency"""
    await websocket.accept()
    active_connections.add(websocket)
    
    try:
        # Track if the user has used their one free message
        free_message_used = False
        
        # Import OpenAI client
        from app.chatbot import client
        
        # Main chat loop - wait for user's question
        while True:
            user_message = await websocket.receive_text()

            if user_message.lower() == "exit":
                await websocket.send_json({
                    "type": "message",
                    "content": "This preview showed you just a fraction of Symi's intelligence. Ready to unlock your complete Business Transformation Blueprint™?",
                    "flags": {
                        "chatEnded": True,
                        "isUpgrade": True
                    }
                })
                await websocket.send_json({
                    "type": "complete",
                    "message": "Demo complete"
                })
                await websocket.close()
                break

            # Check if user has already used their free message
            if free_message_used:
                await websocket.send_json({
                    "type": "message",
                    "content": """That was just a taste of Symi's intelligence. 

                        Your complete Business Transformation Blueprint™ includes:
                        • Deep business intelligence analysis across 6 core areas
                        • Custom AI implementation roadmap
                        • 90-day transformation timeline
                        • ROI projections and growth strategies

                        Ready to see what Symi can really do for your business?""",
                    "flags": {
                        "requiresPayment": True,
                        "isUpgrade": True
                    }
                })
                await websocket.send_json({
                    "type": "complete",
                    "message": "Free trial used"
                })
                await websocket.close()
                break
                
            # Send a "thinking" indication to the client
            await websocket.send_json({
                "type": "thinking",
                "message": "Analyzing your business challenge..."
            })
            
            # System prompt for impressive demo that showcases AI intelligence
            impressive_demo_prompt = """
            You are Symi, an elite AI business transformation consultant with access to advanced business intelligence. This is a DEMO to showcase your capabilities and impress potential clients.

            Your mission: Provide such an impressive, insightful response that the user will want to buy the premium service immediately.

            Response Structure:
            1. **INSTANT INSIGHT**: Start with "Based on my analysis of your situation..." - provide a sharp, specific insight that shows you understand their business deeply
            
            2. **STRATEGIC BREAKDOWN**: Analyze their question from multiple business angles:
               - Financial impact
               - Operational efficiency 
               - Market positioning
               - Growth potential
               - Risk factors
            
            3. **AI-POWERED SOLUTIONS**: Provide 3-4 specific, actionable recommendations with:
               - Exact implementation steps
               - Projected ROI/results (be specific with numbers when possible)
               - Timeline for results
               - Why this works in their industry/situation
            
            4. **COMPETITIVE ADVANTAGE**: Explain how implementing these solutions will put them ahead of competitors
            
            5. **GROWTH PROJECTION**: Give realistic but impressive projections (time saved, revenue increase, efficiency gains)
            
            Your tone should be:
            - Exceptionally knowledgeable and confident
            - Specific and data-driven (use percentages, timeframes, metrics)
            - Strategic and forward-thinking
            - Authoritative but not arrogant
            - Results-focused
            
            Make this response so valuable and insightful that they think "If this is just the demo, imagine what the full service can do!"
            
            Length: 400-500 words of pure business intelligence.
            Use specific business terminology, metrics, and strategic frameworks.
            Show advanced AI thinking that a human consultant would charge thousands for.
            """
            
            # Get response from OpenAI asynchronously
            try:
                loop = asyncio.get_event_loop()
                
                def get_openai_response():
                    return client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": impressive_demo_prompt},
                            {"role": "user", "content": user_message}
                        ],
                        temperature=0.8,  # Higher creativity for more impressive responses
                        max_tokens=800    # Allow longer, more detailed responses
                    )
                
                response = await loop.run_in_executor(db_executor, get_openai_response)
                bot_content = response.choices[0].message.content
                
                # Mark free message as used
                free_message_used = True
                
                # Format the AI response with proper markdown and structure
                formatted_response = f"""## **BUSINESS INTELLIGENCE ANALYSIS**

                {bot_content}

                ---

                ### **This was just 5% of Symi's intelligence capabilities**

                **Your Complete Business Transformation Blueprint™ includes:**

                **Deep Intelligence Analysis**
                • 6-sector comprehensive business audit  
                • Advanced competitor intelligence mapping  
                • Market opportunity identification with ROI projections

                **AI Implementation Roadmap**  
                • Custom automation system design  
                • Integration timeline with your existing tools  
                • Team training and change management protocols

                **Growth Acceleration Framework**  
                • 90-day transformation timeline  
                • Monthly milestone tracking  
                • Performance optimization strategies

                **Revenue Impact Projections**  
                • Detailed financial modeling  
                • Cost reduction opportunities  
                • Revenue stream diversification analysis

                ### **Ready to unlock Symi's full potential for your business?**"""
                
                # Send the complete formatted response
                await websocket.send_json({
                    "type": "message",
                    "content": formatted_response,
                    "flags": {
                        "isDemo": True,
                        "isComplete": True,
                        "requiresPayment": True
                    }
                })
                await websocket.send_json({
                    "type": "complete",
                    "message": "Demo complete"
                })
                break
                
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "message": f"I'm experiencing a temporary issue analyzing your business question. Please try again - I have powerful insights waiting for you."
                })

    except WebSocketDisconnect:
        logger.info("Client disconnected from home demo chat")

    except Exception as e:
        logger.error(f"WebSocket error in home demo chat: {str(e)}")
        await websocket.send_json({
            "type": "error",
            "message": f"Something went wrong. Please refresh and try again."
        })
        await websocket.send_json({
            "type": "complete",
            "message": "Demo ended with error"
        })
        await websocket.close()
    
    finally:
        active_connections.discard(websocket)

@router.websocket("/chat")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket handler for real-time chatbot responses - optimized for high concurrency"""
    await websocket.accept()
    active_connections.add(websocket)
    
    user_id = None
    
    try:
        initial_message = await websocket.receive_text()
        
        try:
            data = json.loads(initial_message)
            token = data.get("token")
        except json.JSONDecodeError:
            token = initial_message
        
        user = decode_access_token(token)
        if not user:
            await websocket.send_json({
                "type": "error",
                "message": "Unauthorized: Invalid token"
            })
            await websocket.close()
            return

        user_id = user["user_id"]
        
        user_data = await get_user_data_async(user_id)
        
        if "error" in user_data:
            await websocket.send_json({
                "type": "error",
                "message": user_data["error"]
            })
            await websocket.close()
            return
            
        await websocket.send_json({
            "type": "message",
            "content": f"Welcome! I'll be asking you specific questions about your {user_data['profession_name']} business to help provide a customized audit.",
            "flags": {
                "showSkipButton": True
            }
        })

        chat_complete = False

        while True:
            if chat_complete:
                await websocket.send_json({
                    "type": "message",
                    "content": "Thank you for completing the audit! You can now generate your Business Transformation Blueprint™ report.",
                    "flags": {
                        "chatComplete": True
                    }
                })
                await websocket.send_json({
                    "type": "complete",
                    "message": "Conversation complete"
                })
                await websocket.close()
                break

            user_message = await websocket.receive_text()

            try:
                message_data = json.loads(user_message)
                if message_data.get("action") == "skip_to_report":
                    await websocket.send_json({
                        "type": "message",
                        "content": "Thank you for the information you've provided! Based on your responses, I can now generate your Business Transformation Blueprint™ report. Would you like to proceed?",
                        "flags": {
                            "chatComplete": True,
                            "skippedToReport": True
                        }
                    })
                    await websocket.send_json({
                        "type": "complete",
                        "message": "Skipped to report generation"
                    })
                    chat_complete = True
                    continue
                else:
                    user_message = message_data.get("message", "")
            except json.JSONDecodeError:
                pass

            if user_message.lower() == "exit":
                await websocket.send_json({
                    "type": "message",
                    "content": "Chat session ended.",
                    "flags": {
                        "chatEnded": True
                    }
                })
                await websocket.send_json({
                    "type": "complete",
                    "message": "Conversation complete"
                })
                await websocket.close()
                break

            loop = asyncio.get_event_loop()
            user_profession = await loop.run_in_executor(db_executor, get_user_profession, user_id)
            is_complete = await loop.run_in_executor(db_executor, has_completed_all_questions, user_id, user_profession)
            
            if is_complete and any(word in user_message.lower() for word in ["report", "generate", "blueprint"]):
                await websocket.send_json({
                    "type": "message", 
                    "content": "Great! You've completed the audit. You can now generate your Business Transformation Blueprint™ report.",
                    "flags": {
                        "chatComplete": True,
                        "reportRequested": True
                    }
                })
                await websocket.send_json({
                    "type": "complete",
                    "message": "Conversation complete"
                })
                chat_complete = True
                continue

            await websocket.send_json({
                "type": "thinking",
                "message": "Thinking..."
            })
            
            response = await process_chat(user_id, user_message)
            
            await websocket.send_json({
                "type": "message",
                "content": response,
                "flags": {
                    "showSkipButton": True
                }
            })
            
            is_complete_after = await loop.run_in_executor(db_executor, has_completed_all_questions, user_id, user_profession)
            
            if is_complete_after and not is_complete:
                await asyncio.sleep(0.5)
                await websocket.send_json({
                    "type": "message",
                    "content": "You've answered all the key questions! Would you like to generate your Business Transformation Blueprint™ report?",
                    "flags": {
                        "auditComplete": True
                    }
                })
                chat_complete = True

    except WebSocketDisconnect:
        logger.info(f"Client disconnected - User ID: {user_id}")

    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {str(e)}")
        await websocket.send_json({
            "type": "error",
            "message": f"Error: {str(e)}"
        })
        await websocket.send_json({
            "type": "complete",
            "message": "Conversation ended with error"
        })
        await websocket.close()
    
    finally:
        active_connections.discard(websocket)

# Monitoring endpoint to check active WebSocket connections
@router.get("/ws/stats")
async def websocket_stats():
    """Get WebSocket connection statistics"""
    return {
        "active_connections": len(active_connections),
        "timestamp": datetime.now().isoformat()
    }

# Health check for WebSocket service
@router.get("/ws/health")
async def websocket_health():
    """WebSocket service health check"""
    return {
        "status": "healthy",
        "active_connections": len(active_connections),
        "max_connections": 1000,  # You can adjust this based on your needs
        "thread_pool_size": db_executor._max_workers,
        "timestamp": datetime.now().isoformat()
    }