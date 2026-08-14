'use client';

import { type ComponentProps } from 'react';
import { AnimatePresence } from 'motion/react';
import { type AgentState, type ReceivedMessage } from '@livekit/components-react';
import { AgentChatIndicator } from '@/components/agents-ui/agent-chat-indicator';
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from '@/components/ai-elements/conversation';
import { Message, MessageContent, MessageResponse } from '@/components/ai-elements/message';

type SpeakerName = 'Anisha' | 'Arjun';

const SPEAKER_PREFIX_PATTERN = /^\s*(Anisha|Arjun)\s*[-:]\s*/i;
const TOOL_LEAK_PATTERN =
  /^(transfer_to_crop_specialist|search_web|create_escalation|save_caller_info|forget_me)\b/i;
const DEFAULT_ASSISTANT_SPEAKER: SpeakerName = 'Anisha';

function toSpeakerName(value: string | undefined): SpeakerName | null {
  if (!value) return null;

  const normalized = value.trim().toLowerCase();
  if (normalized === 'anisha') return 'Anisha';
  if (normalized === 'arjun') return 'Arjun';

  return null;
}

function getParticipantSpeaker(from: ReceivedMessage['from']): SpeakerName | null {
  const participant = from as
    | {
        isLocal?: boolean;
        name?: string;
        identity?: string;
        attributes?: Record<string, string>;
      }
    | undefined;

  return (
    toSpeakerName(participant?.attributes?.speaker) ??
    toSpeakerName(participant?.name) ??
    toSpeakerName(participant?.identity)
  );
}

function isLocalParticipant(from: ReceivedMessage['from']): boolean {
  return (
    (
      from as
        | {
            isLocal?: boolean;
          }
        | undefined
    )?.isLocal === true
  );
}

function formatAssistantMessage(
  message: string,
  fallbackSpeaker: SpeakerName
): { speaker: SpeakerName; text: string } {
  let text = message.trim();
  let speaker = fallbackSpeaker;
  let match = text.match(SPEAKER_PREFIX_PATTERN);

  while (match) {
    const detectedSpeaker = toSpeakerName(match[1]);
    if (detectedSpeaker) {
      speaker = detectedSpeaker;
    }

    text = text.slice(match[0].length).trimStart();
    match = text.match(SPEAKER_PREFIX_PATTERN);
  }

  const lowerText = text.toLowerCase();
  if (/\bmain\s+arjun\s+hoon\b/.test(lowerText) || /\bi\s+am\s+arjun\b/.test(lowerText)) {
    speaker = 'Arjun';
  } else if (/\bmain\s+anisha\s+hoon\b/.test(lowerText) || /\bi\s+am\s+anisha\b/.test(lowerText)) {
    speaker = 'Anisha';
  }

  return { speaker, text };
}

function stripSpeakerPrefix(message: string): string {
  let text = message.trim();
  let match = text.match(SPEAKER_PREFIX_PATTERN);

  while (match) {
    text = text.slice(match[0].length).trimStart();
    match = text.match(SPEAKER_PREFIX_PATTERN);
  }

  return text;
}

function shouldShowMessage(message: string): boolean {
  const trimmed = message.trim();
  const unprefixed = stripSpeakerPrefix(trimmed);

  if (!unprefixed) return false;
  if (unprefixed.startsWith('function=')) return false;
  if (unprefixed.startsWith('(function=')) return false;
  if (unprefixed.startsWith('<function')) return false;
  if (unprefixed.startsWith('{"function"')) return false;
  if (unprefixed.startsWith('[SYSTEM')) return false;
  if (/\(function=\w+>/.test(unprefixed)) return false;
  if (TOOL_LEAK_PATTERN.test(unprefixed)) return false;
  if (/crop disease specialist\s+24 ghante/i.test(unprefixed)) return false;

  return true;
}

export interface AgentChatTranscriptProps extends ComponentProps<'div'> {
  agentState?: AgentState;
  messages?: ReceivedMessage[];
  className?: string;
}

export function AgentChatTranscript({
  agentState,
  messages = [],
  className,
  ...props
}: AgentChatTranscriptProps) {
  const filtered = messages.filter(({ message }) => {
    if (!message) return false;
    return shouldShowMessage(message);
  });

  let currentAssistantSpeaker = DEFAULT_ASSISTANT_SPEAKER;

  return (
    <Conversation className={className} {...props}>
      <ConversationContent>
        {filtered.map((receivedMessage) => {
          const { id, timestamp, from, message } = receivedMessage;
          const locale = typeof navigator !== 'undefined' ? navigator.language : 'en-US';
          const isUser = isLocalParticipant(from);
          const messageOrigin = isUser ? 'user' : 'assistant';
          const participantSpeaker = getParticipantSpeaker(from);
          const assistantMessage = isUser
            ? null
            : formatAssistantMessage(message, participantSpeaker ?? currentAssistantSpeaker);

          if (assistantMessage) {
            currentAssistantSpeaker = assistantMessage.speaker;
          }

          const displayMessage = assistantMessage
            ? `${assistantMessage.speaker} - ${assistantMessage.text}`
            : message;
          const time = new Date(timestamp);
          const title = time.toLocaleTimeString(locale, { timeStyle: 'full' });

          return (
            <Message key={id} title={title} from={messageOrigin}>
              <MessageContent>
                <MessageResponse>{displayMessage}</MessageResponse>
              </MessageContent>
            </Message>
          );
        })}
        <AnimatePresence>
          {agentState === 'thinking' && <AgentChatIndicator size="sm" />}
        </AnimatePresence>
      </ConversationContent>
      <ConversationScrollButton />
    </Conversation>
  );
}
