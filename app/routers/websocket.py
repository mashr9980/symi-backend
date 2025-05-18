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
    """WebSocket handler for home page demo chat with one-time usage."""
    await websocket.accept()

    try:
        # First message should contain token (if user is authenticated) or be empty
        initial_message = await websocket.receive_text()
        
        # Track if the user has used their one free message
        free_message_used = False
        
        # Send initial greeting
        await websocket.send_json({
            "type": "message",
            "content": "Welcome to the Business Transformation Blueprint™ AI Assistant Demo! I can help analyze your business and identify AI-powered transformation opportunities. Ask me anything about optimizing your business operations."
        })

        # Main chat loop
        while True:
            user_message = await websocket.receive_text()

            if user_message.lower() == "exit":
                await websocket.send_json({
                    "type": "message",
                    "content": "Thank you for trying our demo! For a complete business audit, please sign up for our service.",
                    "flags": {
                        "chatEnded": True
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
                    "content": "You've used your free demo message. To continue using our AI business assistant and get your complete Business Transformation Blueprint™, please upgrade to a premium plan.",
                    "flags": {
                        "requiresPayment": True
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
                "message": "Thinking..."
            })
            
            # Call OpenAI API for demo response
            from app.chatbot import client
            
            # Simplified system prompt for demo purposes
            system_content = """
            You are an AI business consultant specialized in identifying AI-powered transformation opportunities.
            
            This is a DEMO conversation, so:
            1. Keep responses concise (max 3-4 paragraphs)
            2. Focus on showing how AI can transform business operations
            3. Highlight the value of a complete business audit
            4. End your response with a subtle encouragement to sign up for the full service
            
            Remember this is just a demo to showcase capabilities. The full service provides:
            - Detailed business audit
            - Custom transformation blueprint
            - AI implementation roadmap
            - ROI projections
            """
            
            # Get response from OpenAI
            try:
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": user_message}
                    ]
                )
                
                bot_content = response.choices[0].message.content
                
                # Mark free message as used
                free_message_used = True
                
                # Send the complete response
                await websocket.send_json({
                    "type": "message",
                    "content": bot_content,
                    "flags": {
                        "isDemo": True,
                        "trialUsed": True
                    }
                })
                
                # Show upgrade prompt after sending the response
                await asyncio.sleep(0.5)  # Small delay before sending follow-up
                await websocket.send_json({
                    "type": "message",
                    "content": "Thank you for trying our demo! To continue using our AI business assistant and get your complete Business Transformation Blueprint™, please upgrade to a premium plan.",
                    "flags": {
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
                    "message": f"Sorry, I encountered an error: {str(e)}"
                })

    except WebSocketDisconnect:
        print("Client disconnected from home demo chat")

    except Exception as e:
        print(f"WebSocket error in home demo chat: {str(e)}")
        await websocket.send_json({
            "type": "error",
            "message": f"Error: {str(e)}"
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