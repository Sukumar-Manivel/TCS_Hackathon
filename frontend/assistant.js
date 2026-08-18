// ============================================================
// AI ASSISTANT
// Customer Feedback Intelligence Platform
//
// Frontend responsibilities:
//   1. Capture user messages
//   2. Maintain chat history
//   3. Send messages to FastAPI
//   4. Render AI responses
//
// Backend responsibilities:
//   1. Read current STORE / LangGraph analysis
//   2. Build project context
//   3. Call OpenRouter
//   4. Return the AI response
//
// IMPORTANT:
// The OpenRouter API key is NEVER stored in this file.
// ============================================================


// ============================================================
// HTML ESCAPING
// ============================================================

function escapeHtml(s) {
  if (typeof s !== 'string') {
    return '';
  }

  return s.replace(
    /[&<>"']/g,
    c => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[c])
  );
}


// ============================================================
// SEND CHAT MESSAGE
// ============================================================

async function sendChat() {

  const input = document.getElementById('chat-input');

  if (!input) {
    console.error('chat-input element not found');
    return;
  }

  const text = input.value.trim();

  if (!text) {
    return;
  }


  // ----------------------------------------------------------
  // Make sure chat history exists
  // ----------------------------------------------------------

  if (!state.chatHistory) {
    state.chatHistory = [];
  }


  // ----------------------------------------------------------
  // Add user message
  // ----------------------------------------------------------

  state.chatHistory.push({
    role: 'user',
    content: text
  });

  input.value = '';


  // ----------------------------------------------------------
  // Render user message immediately
  // ----------------------------------------------------------

  if (typeof renderChatMessages === 'function') {
    renderChatMessages();
  }


  // ----------------------------------------------------------
  // Show typing indicator
  // ----------------------------------------------------------

  const typing =
    document.getElementById('typing-indicator');

  if (typing) {
    typing.style.display = 'flex';
  }


  // ----------------------------------------------------------
  // Scroll chat to bottom
  // ----------------------------------------------------------

  const chatMessages =
    document.getElementById('chat-messages');

  if (chatMessages) {
    chatMessages.scrollTop =
      chatMessages.scrollHeight;
  }


  try {

    // ========================================================
    // SEND REQUEST TO FASTAPI
    // ========================================================

    const response = await fetch(
      'http://127.0.0.1:8000/api/chat',
      {
        method: 'POST',

        headers: {
          'Content-Type': 'application/json'
        },

        body: JSON.stringify({
          messages: state.chatHistory
        })
      }
    );


    // ========================================================
    // HANDLE BACKEND ERROR
    // ========================================================

    if (!response.ok) {

      let errorMessage =
        'The AI assistant could not process your request.';

      try {

        const errorData =
          await response.json();

        if (errorData.detail) {
          errorMessage = errorData.detail;
        }

      } catch (_) {
        // Ignore JSON parsing errors
      }

      throw new Error(errorMessage);
    }


    // ========================================================
    // READ FASTAPI RESPONSE
    // ========================================================

    const data =
      await response.json();


    const reply =
      typeof data.reply === 'string'
        ? data.reply.trim()
        : 'I could not generate a response.';


    // ========================================================
    // ADD AI RESPONSE TO CHAT HISTORY
    // ========================================================

    state.chatHistory.push({
      role: 'assistant',
      content: reply
    });


  } catch (error) {

    console.error(
      'AI Assistant error:',
      error
    );


    // --------------------------------------------------------
    // Show friendly error in chat
    // --------------------------------------------------------

    state.chatHistory.push({
      role: 'assistant',
      content:
        'I couldn’t connect to the AI assistant right now. Please check that the FastAPI server is running and try again.'
    });

  } finally {

    // ========================================================
    // HIDE TYPING INDICATOR
    // ========================================================

    if (typing) {
      typing.style.display = 'none';
    }


    // ========================================================
    // RENDER FINAL CHAT
    // ========================================================

    if (typeof renderChatMessages === 'function') {
      renderChatMessages();
    }


    // ========================================================
    // SCROLL TO BOTTOM
    // ========================================================

    if (chatMessages) {
      chatMessages.scrollTop =
        chatMessages.scrollHeight;
    }
  }
}


// ============================================================
// ENTER KEY SUPPORT
// ============================================================

function handleChatKeydown(event) {

  if (event.key === 'Enter' && !event.shiftKey) {

    event.preventDefault();

    sendChat();
  }
}


// ============================================================
// INITIALIZE CHAT
// ============================================================

function initializeAssistant() {

  const input =
    document.getElementById('chat-input');

  if (!input) {
    console.warn(
      'AI Assistant: chat-input not found.'
    );

    return;
  }


  // ----------------------------------------------------------
  // Enter = Send
  // Shift + Enter = New line
  // ----------------------------------------------------------

  input.addEventListener(
    'keydown',
    handleChatKeydown
  );


  // ----------------------------------------------------------
  // Make sure state exists
  // ----------------------------------------------------------

  if (typeof state !== 'undefined') {

    if (!state.chatHistory) {
      state.chatHistory = [];
    }

  }


  console.log(
    'AI Assistant initialized.'
  );
}


// ============================================================
// AUTO INITIALIZATION
// ============================================================

if (document.readyState === 'loading') {

  document.addEventListener(
    'DOMContentLoaded',
    initializeAssistant
  );

} else {

  initializeAssistant();
}