from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from app.chatbot import get_chat_history, process_chat, get_user_profession, has_completed_all_questions
from app.auth import decode_access_token
from app.database import get_db_connection
import json
import asyncio
from datetime import datetime

router = APIRouter(tags=["Chat Websocket"])

@router.websocket("/home-chat")
async def home_websocket_endpoint(websocket: WebSocket):
    """WebSocket handler for home page demo chat - user asks one question, AI responds as business expert."""
    await websocket.accept()

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
            
            # Get response from OpenAI
            try:
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": impressive_demo_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.8,  # Higher creativity for more impressive responses
                    max_tokens=800    # Allow longer, more detailed responses
                )
                
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
        print("Client disconnected from home demo chat")

    except Exception as e:
        print(f"WebSocket error in home demo chat: {str(e)}")
        await websocket.send_json({
            "type": "error",
            "message": f"Something went wrong. Please refresh and try again. Error: {str(e)}"
        })
        await websocket.send_json({
            "type": "complete",
            "message": "Demo ended with error"
        })
        await websocket.close()

@router.websocket("/chat")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket handler for real-time chatbot responses without streaming."""
    await websocket.accept()

    try:
        # First message should contain token
        initial_message = await websocket.receive_text()
        
        try:
            # Parse the initial message as JSON
            data = json.loads(initial_message)
            token = data.get("token")
        except json.JSONDecodeError:
            # If not JSON, assume it's just the token
            token = initial_message
        
        # Validate token
        user = decode_access_token(token)
        if not user:
            await websocket.send_json({
                "type": "error",
                "message": "Unauthorized: Invalid token"
            })
            await websocket.close()
            return

        user_id = user["user_id"]
        
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if user is suspended
        cursor.execute("SELECT status FROM users WHERE id = %s", (user_id,))
        status = cursor.fetchone()
        
        if not status or status[0] == "suspended":
            cursor.close()
            conn.close()
            await websocket.send_json({
                "type": "error",
                "message": "Your account is suspended. Contact admin."
            })
            await websocket.close()
            return
        
        # Check if user has a profession set (should be set during signup)
        cursor.execute("""
            SELECT p.name 
            FROM user_profession up
            JOIN professions p ON up.profession_id = p.id
            WHERE up.user_id = %s
        """, (user_id,))
        
        profession_result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not profession_result:
            await websocket.send_json({
                "type": "error",
                "message": "No profession is set for your account. This is unusual and might be a system error since profession should be selected during signup."
            })
            await websocket.close()
            return
            
        # Greeting with profession-specific message
        await websocket.send_json({
            "type": "message",
            "content": f"Welcome! I'll be asking you specific questions about your {profession_result[0]} business to help provide a customized audit."
        })

        # New variable to track whether chat has ended
        chat_complete = False

        while True:
            if chat_complete:
                # If chat is already complete, send final message with flag
                await websocket.send_json({
                    "type": "message",
                    "content": "Thank you for completing the audit! You can now generate your Business Transformation Blueprint™ report.",
                    "flags": {
                        "chatComplete": True
                    }
                })
                # Send the complete type message to indicate conversation has ended
                await websocket.send_json({
                    "type": "complete",
                    "message": "Conversation complete"
                })
                await websocket.close()
                break

            user_message = await websocket.receive_text()

            if user_message.lower() == "exit":
                await websocket.send_json({
                    "type": "message",
                    "content": "Chat session ended.",
                    "flags": {
                        "chatEnded": True
                    }
                })
                # Send the complete type message to indicate conversation has ended
                await websocket.send_json({
                    "type": "complete",
                    "message": "Conversation complete"
                })
                await websocket.close()
                break

            # Check if user has completed all questions
            user_profession = get_user_profession(user_id)
            is_complete = has_completed_all_questions(user_id, user_profession)
            
            # If user already completed the audit and says a trigger word like "report" or "generate"
            if is_complete and any(word in user_message.lower() for word in ["report", "generate", "blueprint"]):
                await websocket.send_json({
                    "type": "message", 
                    "content": "Great! You've completed the audit. You can now generate your Business Transformation Blueprint™ report.",
                    "flags": {
                        "chatComplete": True,
                        "reportRequested": True
                    }
                })
                # Send the complete type message to indicate conversation has ended
                await websocket.send_json({
                    "type": "complete",
                    "message": "Conversation complete"
                })
                chat_complete = True
                continue

            # Send a "thinking" indication to the client
            await websocket.send_json({
                "type": "thinking",
                "message": "Thinking..."
            })
            
            # Get response without streaming
            response = process_chat(user_id, user_message)
            
            # Send the complete response
            await websocket.send_json({
                "type": "message",
                "content": response
            })
            
            # After response is sent, check if all questions have been answered
            is_complete_after = has_completed_all_questions(user_id, user_profession)
            
            # If chat just became complete with this message
            if is_complete_after and not is_complete:
                await asyncio.sleep(0.5)  # Small delay before sending completion message
                await websocket.send_json({
                    "type": "message",
                    "content": "You've answered all the key questions! Would you like to generate your Business Transformation Blueprint™ report?",
                    "flags": {
                        "auditComplete": True
                    }
                })
                chat_complete = True

    except WebSocketDisconnect:
        print("Client disconnected")

    except Exception as e:
        print(f"WebSocket error: {str(e)}")
        await websocket.send_json({
            "type": "error",
            "message": f"Error: {str(e)}"
        })
        # Send the complete type message even in error case
        await websocket.send_json({
            "type": "complete",
            "message": "Conversation ended with error"
        })
        await websocket.close()