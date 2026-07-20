"""
Instance Command Executor Module for Mneme Memory System

Handles AI-initiated @commands during conversation:
- Parses commands from AI response text
- Executes command loop with iteration limits
- Supports both streaming and non-streaming modes
- Handles recursive AI calls for retrieval commands

SPEC ALIGNMENT:
- Line 91-96: Instance autonomy for certain settings
- Lines 73-82: All commands available to instance

USAGE:
    executor = InstanceExecutor(command_handler, database, config)
    response, commands = executor.execute_loop(ai_response, context, ai_caller)
    # Or with streaming:
    response, commands = yield from executor.execute_loop_stream(ai_response, context, ai_caller)
"""

from typing import Dict, List, Tuple, Callable, Optional, Generator, Any
import re
import json


class ExecutorError(Exception):
    """Custom exception for executor errors."""
    pass


class InstanceExecutor:
    """
    Handles AI-initiated command execution during conversation.

    This class:
    - Parses @commands from AI response text
    - Executes commands via CommandHandler
    - Handles recursive AI calls for retrieval commands
    - Tracks command usage statistics
    - Applies @remember self and @tag self to AI messages
    """

    # Commands that return data and may trigger recursive AI calls
    # Phase 7: Added "file" and "describe" for file viewing
    RETRIEVAL_COMMANDS = ["recall", "review", "graph", "concept", "file", "describe", "run", "entity", "help", "view"]

    def __init__(self, command_handler, database, config: Dict):
        """
        Initialize instance executor.

        Args:
            command_handler: CommandHandler instance
            database: Database instance
            config: Configuration dictionary
        """
        self.command_handler = command_handler
        self.db = database
        self.config = config

        # Max iterations from config
        self.max_iterations = config.get("commands", {}).get("max_iterations", 6)

        # Side-channel for @run output embedding (set by _build_continuation_prompt)
        self._last_run_embed = None

    def parse_commands(self, text: str) -> List[str]:
        """
        Parse @commands from AI response text.

        Args:
            text: AI's response text

        Returns:
            List[str]: List of command strings found (e.g., ["@recall crows", "@remember Important"])

        DETECTION:
        - Commands must start at beginning of line (after newline or at text start)
        - For multi-line commands (like @concept create with pipes), captures entire command
        - Multi-line @note...@endnote blocks are extracted in a pre-pass (Phase 11)
        - Matches any command that CommandHandler recognizes (future-proof!)

        EXAMPLES:
            "Let me check: @recall crows" → ["@recall crows"]
            "@recall crows\\nBased on that..." → ["@recall crows"]
            "@concept create foo | kw1, kw2 | definition" → ["@concept create foo | kw1, kw2 | definition"]
            "We should @recall more" → [] (not at line start)
            "@note Preferences\\n- Dark themes\\n@endnote" → ["@note Preferences\\n- Dark themes"]
        """
        commands = []

        # Pre-pass: Extract multi-line @note...@endnote blocks (Phase 11)
        # These span multiple lines and must be captured before single-line parsing.
        # Negative lookahead excludes "remove" and "clear" (those are single-line).
        note_pattern = r'^@note\s+(?!remove\b|clear\b)(.+)\n([\s\S]*?)^@endnote\s*$'
        remaining_text = text

        for match in re.finditer(note_pattern, text, re.MULTILINE):
            section_name = match.group(1).strip()
            content = match.group(2).strip()
            command_str = f"@note {section_name}\n{content}"
            commands.append(command_str)
            # Remove matched block so standard parsing doesn't hit @endnote
            remaining_text = remaining_text.replace(match.group(0), "", 1)

        # Pre-pass: Extract multi-line @artifact...@endartifact blocks
        artifact_pattern = r'^@artifact\s+(.+)\n([\s\S]*?)^@endartifact\s*$'

        for match in re.finditer(artifact_pattern, remaining_text, re.MULTILINE):
            header = match.group(1).strip()
            content = match.group(2).strip()
            command_str = f"@artifact {header}\n{content}"
            commands.append(command_str)
            remaining_text = remaining_text.replace(match.group(0), "", 1)

        # Pre-pass: Extract multi-line @run...@endrun blocks
        run_pattern = r'^@run\s*\n([\s\S]*?)^@endrun\s*$'

        for match in re.finditer(run_pattern, remaining_text, re.MULTILINE):
            code = match.group(1).strip()
            command_str = f"@run {code}"
            commands.append(command_str)
            remaining_text = remaining_text.replace(match.group(0), "", 1)

        # Standard single-line command parsing on remaining text
        # Pattern: @ at line start, followed by command word, then rest of line
        # For @concept create with pipes, this captures the entire line including pipes
        pattern = r'^@\w+(?:\s+[^\n]*)?$'

        for match in re.finditer(pattern, remaining_text, re.MULTILINE):
            command_str = match.group(0).strip()
            # Verify it's a valid command using CommandHandler
            if self.command_handler.is_command(command_str):
                commands.append(command_str)

        return commands

    def execute_loop(
        self,
        ai_response: str,
        context: Dict,
        ai_caller: Callable[[Dict, str, bool], str],
        iteration: int = 0
    ) -> Tuple[str, List[Dict]]:
        """
        Execute instance command loop (non-streaming version).

        Args:
            ai_response: AI's response text
            context: Current context dict
            ai_caller: Callback function to call AI - signature: (context, current_input, stream) -> response
            iteration: Current iteration count (starts at 0)

        Returns:
            tuple: (final_response, commands_used_list)

        FLOW:
        1. Parse AI response for @commands
        2. If commands found:
            a. Print notification: "Instance used @recall crows"
            b. Execute command locally
            c. Add result to context
            d. Call AI again with updated context
            e. Repeat until no commands or max iterations
        3. Return final response
        """
        commands_used = []

        # Check for max iterations
        if iteration >= self.max_iterations:
            print(f"  Max instance command iterations ({self.max_iterations}) reached")
            return ai_response, commands_used

        # Parse commands from AI response
        found_commands = self.parse_commands(ai_response)

        if not found_commands:
            return ai_response, commands_used

        # Print notification that instance is using commands
        print(f"🤖 Instance is processing commands...")

        # CRITICAL: Don't strip commands from response!
        # Stripping creates "learned helplessness" - instance sees blank where commands were
        ai_response_clean = ai_response  # Keep original response with commands intact

        # Execute ALL commands first (don't return early)
        retrieval_result = None

        for command_str in found_commands:
            print(f"   ↳ Instance used {command_str}")

            try:
                result = self.command_handler.handle_command(command_str, marked_by="instance")

                # Handle error case
                if isinstance(result, str):
                    print(f"      ↳ Error: {result}")
                    commands_used.append({
                        "command": command_str,
                        "iteration": iteration + 1,
                        "success": False,
                        "error": result
                    })
                    continue

                # Track command usage
                cmd_info = self._build_command_info(command_str, result, iteration)
                commands_used.append(cmd_info)

                # Print result
                self._print_result(result)

                # Check if this is a retrieval command (needs recursion)
                if self._is_retrieval_result(result) and not retrieval_result:
                    retrieval_result = (command_str, result)

            except Exception as e:
                print(f"      ↳ Error executing command: {e}")
                commands_used.append({
                    "command": command_str,
                    "iteration": iteration + 1,
                    "success": False,
                    "error": str(e)
                })

        # Handle recursion if we had a retrieval command
        if retrieval_result:
            command_str, result = retrieval_result

            self._last_run_embed = None  # Reset before building prompt
            continuation_data = self._build_continuation_prompt(ai_response_clean, command_str, result, iteration)
            run_embed = self._last_run_embed  # Capture before next iteration clears it

            # Handle multimodal vs text-only continuation (Phase 7)
            if isinstance(continuation_data, dict):
                # Multimodal continuation (has image content)
                continuation_prompt = continuation_data.get("text", "")
                content_blocks = continuation_data.get("content_blocks", [])

                # Pass content blocks through context for multimodal handling
                if content_blocks:
                    context["_continuation_content_blocks"] = content_blocks
            else:
                continuation_prompt = continuation_data

            print(f"💭 Calling AI again with {result['command']} results...")

            try:
                new_ai_response = ai_caller(context, continuation_prompt, False)

                # Clean up context
                context.pop("_continuation_content_blocks", None)

                # Recursively check for more commands
                continuation_response, more_commands = self.execute_loop(
                    new_ai_response,
                    context,
                    ai_caller,
                    iteration + 1
                )

                # Embed @run output in stored response (persists in active context, stripped on tier transition)
                # Strip previous embeds — only the last @run result matters for ongoing discussion
                clean = re.sub(r'\n*\[run output\]\n[\s\S]*?\[/run output\]', '', ai_response_clean)
                embed = run_embed or ""
                combined_response = clean + embed + "\n\n" + continuation_response
                commands_used.extend(more_commands)
                return combined_response, commands_used

            except Exception as e:
                print(f"   Error in follow-up AI call: {e}")
                context.pop("_continuation_content_blocks", None)
                return ai_response_clean, commands_used

        # Check for NEW commands (not ones we just processed)
        if iteration < self.max_iterations - 1:
            remaining_commands = self.parse_commands(ai_response_clean)
            new_commands = [cmd for cmd in remaining_commands if cmd not in found_commands]
            if new_commands:
                return self.execute_loop(ai_response_clean, context, ai_caller, iteration + 1)

        return ai_response_clean, commands_used

    def execute_loop_stream(
        self,
        ai_response: str,
        context: Dict,
        ai_caller: Callable[[Dict, str, bool], str],
        iteration: int = 0
    ) -> Generator[Dict, None, Tuple[str, List[Dict]]]:
        """
        Execute instance command loop with streaming notifications.

        Args:
            ai_response: AI's response text
            context: Current context dict
            ai_caller: Callback function to call AI - signature: (context, current_input, stream) -> response
            iteration: Current iteration count (starts at 0)

        Yields:
            dict: Notification events {"type": "notification", "data": "..."}

        Returns (via generator return):
            tuple: (final_response, commands_used_list)
        """
        commands_used = []

        # Check for max iterations
        if iteration >= self.max_iterations:
            yield {"type": "notification", "data": f"Wrapped up (hit command limit)"}
            return ai_response, commands_used

        # Parse commands from AI response
        found_commands = self.parse_commands(ai_response)

        if not found_commands:
            return ai_response, commands_used

        # Notify that instance is processing commands
        yield {"type": "notification", "data": "Looking something up"}

        # CRITICAL: Don't strip commands from response!
        ai_response_clean = ai_response

        # Execute ALL commands
        retrieval_result = None

        for command_str in found_commands:
            # Truncate long commands (e.g. @concept create with full definition) for notification
            cmd_display = command_str if len(command_str) <= 80 else command_str[:77] + "..."
            yield {"type": "notification", "data": f"used {cmd_display}"}

            try:
                result = self.command_handler.handle_command(command_str, marked_by="instance")

                # Handle error case
                if isinstance(result, str):
                    yield {"type": "notification", "data": f"Error: {result}"}
                    commands_used.append({
                        "command": command_str,
                        "iteration": iteration + 1,
                        "success": False,
                        "error": result
                    })
                    continue

                # Track command usage
                cmd_info = self._build_command_info(command_str, result, iteration)
                commands_used.append(cmd_info)

                # Yield result notification
                notification = self._format_result_notification(result)
                yield {"type": "notification", "data": notification}

                # Check if this is a retrieval command (needs recursion)
                if self._is_retrieval_result(result) and not retrieval_result:
                    retrieval_result = (command_str, result)

            except Exception as e:
                yield {"type": "notification", "data": f"Error executing command: {e}"}
                commands_used.append({
                    "command": command_str,
                    "iteration": iteration + 1,
                    "success": False,
                    "error": str(e)
                })

        # Handle recursion if we had a retrieval command
        if retrieval_result:
            command_str, result = retrieval_result

            yield {"type": "notification", "data": "Thinking about what they found"}

            self._last_run_embed = None  # Reset before building prompt
            continuation_data = self._build_continuation_prompt(ai_response_clean, command_str, result, iteration)
            run_embed = self._last_run_embed  # Capture before next iteration clears it

            # Handle multimodal vs text-only continuation (Phase 7)
            if isinstance(continuation_data, dict):
                # Multimodal continuation (has image content)
                continuation_prompt = continuation_data.get("text", "")
                content_blocks = continuation_data.get("content_blocks", [])

                # Pass content blocks through context for multimodal handling
                if content_blocks:
                    context["_continuation_content_blocks"] = content_blocks
            else:
                continuation_prompt = continuation_data

            # Stream the recursive AI call (fixes Phase 4.3 streaming bug!)
            try:
                stream = ai_caller(context, continuation_prompt, True)

                # Accumulate response while streaming chunks
                # AIClient yields {"type": "start/chunk/end", "data": ...}
                recursive_response = ""
                for event in stream:
                    if event["type"] == "chunk":
                        chunk = event["data"]
                        recursive_response += chunk
                        yield {"type": "chunk", "data": chunk}
                    elif event["type"] == "start":
                        # Stream started
                        pass
                    elif event["type"] == "notification":
                        yield event
                    elif event["type"] == "error":
                        raise RuntimeError(event.get("data", "Continuation failed"))
                    elif event["type"] == "end":
                        # Stream ended - usage available in event["data"]["usage"]
                        pass

            except Exception as e:
                # Fall back to non-streaming on error
                yield {"type": "notification", "data": "Retrying"}
                recursive_response = ai_caller(context, continuation_prompt, False)

            # Clean up context
            context.pop("_continuation_content_blocks", None)

            # Recurse with new response to check for more commands
            continuation_response, recursive_commands = yield from self.execute_loop_stream(
                recursive_response,
                context,
                ai_caller,
                iteration + 1
            )

            # Embed @run output in stored response (persists in active context, stripped on tier transition)
            embed = run_embed or ""
            combined_response = ai_response_clean + embed + "\n\n" + continuation_response
            return combined_response, commands_used + recursive_commands

        return ai_response_clean, commands_used

    def _build_command_info(self, command_str: str, result: Dict, iteration: int) -> Dict:
        """Build command info dict for tracking."""
        return {
            "command": command_str,
            "iteration": iteration + 1,
            "success": result.get("success", False)
        }

    def _is_retrieval_result(self, result: Dict) -> bool:
        """Check if result is from a retrieval command with data."""
        if not result.get("success"):
            return False

        # Check explicit is_retrieval flag (Phase 7: file commands)
        data = result.get("data", {})
        if isinstance(data, dict) and data.get("is_retrieval"):
            return True

        # Check if command is in retrieval commands list and has data
        if result.get("command") not in self.RETRIEVAL_COMMANDS:
            return False
        return bool(data)

    def _print_result(self, result: Dict):
        """Print result notification to console."""
        if result.get("success"):
            if result["command"] == "recall":
                count = len(result.get("data", {}).get("results", []))
                print(f"      ↳ Found {count} relevant memories")
            elif result["command"] == "remember":
                print(f"      ↳ Marked as high-importance")
            elif result["command"] == "review":
                count = len(result.get("data", []))
                print(f"      ↳ Retrieved {count} messages")
            elif result["command"] == "forget":
                data = result.get("data", {})
                if isinstance(data, dict) and data.get("previews"):
                    count = len(data["previews"])
                    print(f"      ↳ Found {count} memories to review")
                else:
                    print(f"      ↳ Archived to deep storage")
            elif result["command"] == "tag":
                print(f"      ↳ Tags updated")
            elif result["command"] == "modify":
                print(f"      ↳ {result.get('message', 'Memory modified')}")
            elif result["command"] == "view":
                print(f"      ↳ Displaying message details")
            elif result["command"] == "note":
                print(f"      ↳ {result.get('message', 'Note updated')}")
            elif result["command"] == "config":
                print(f"      ↳ Configuration updated")
            elif result["command"] == "file":
                data = result.get("data", {})
                if data.get("is_retrieval"):
                    print(f"      ↳ 📎 Loading file: {data.get('filename', 'unknown')}")
                else:
                    print(f"      ↳ {result.get('message', 'File operation complete')}")
            elif result["command"] == "describe":
                data = result.get("data", {})
                if data.get("is_retrieval"):
                    print(f"      ↳ 📎 Viewing file for description: {data.get('filename', 'unknown')}")
                else:
                    print(f"      ↳ {result.get('message', 'Description updated')}")
            elif result["command"] == "artifact":
                data = result.get("data", {})
                relative_path = data.get("relative_path") or f"{data.get('category', '?')}/{data.get('slug', '?')}/ARTIFACT.md"
                size_bytes = data.get("size_bytes")
                if data.get("verified") and size_bytes is not None:
                    print(f"      ↳ Artifact verified: {relative_path} ({size_bytes} bytes)")
                else:
                    print(f"      ↳ Artifact saved: {relative_path}")
            elif result["command"] == "run":
                data = result.get("data", {})
                rc = data.get("return_code", "?")
                print(f"      ↳ Script finished (exit code {rc})")
            else:
                print(f"      ↳ {result.get('message', 'Executed successfully')}")
        else:
            print(f"      ↳ Failed: {result.get('message', 'Unknown error')}")

    def _format_result_notification(self, result: Dict) -> str:
        """Format result as notification string for streaming."""
        if result.get("success"):
            if result["command"] == "recall":
                count = len(result.get("data", {}).get("results", []))
                return f"Found {count} related memories"
            elif result["command"] == "remember":
                return "Marked as important"
            elif result["command"] == "review":
                count = len(result.get("data", []))
                return f"Pulled up {count} messages"
            elif result["command"] == "forget":
                data = result.get("data", {})
                if isinstance(data, dict) and data.get("previews"):
                    count = len(data["previews"])
                    return f"Found {count} memories to archive"
                return "Archived"
            elif result["command"] == "tag":
                return "Tags updated"
            elif result["command"] == "modify":
                return result.get('message', 'Memory modified')
            elif result["command"] == "view":
                return "Displaying message details"
            elif result["command"] == "concept":
                return result.get('message', 'Updated concept')
            elif result["command"] == "graph":
                return "Graph query executed"
            elif result["command"] == "note":
                return result.get('message', 'Updated note')
            elif result["command"] == "config":
                return "Settings updated"
            elif result["command"] == "file":
                data = result.get("data", {})
                if data.get("is_retrieval"):
                    return f"Opening {data.get('filename', 'unknown')}"
                else:
                    return result.get('message', 'Done')
            elif result["command"] == "describe":
                data = result.get("data", {})
                if data.get("is_retrieval"):
                    return f"Looking at {data.get('filename', 'unknown')}"
                else:
                    return result.get('message', 'Updated description')
            elif result["command"] == "artifact":
                data = result.get("data", {})
                relative_path = data.get("relative_path") or f"{data.get('category', '?')}/{data.get('slug', '?')}/ARTIFACT.md"
                size_bytes = data.get("size_bytes")
                if data.get("verified") and size_bytes is not None:
                    return f"Saved artifact ({size_bytes} bytes)"
                return f"Saved artifact: {relative_path}"
            elif result["command"] == "run":
                data = result.get("data", {})
                rc = data.get("return_code", "?")
                return f"Ran code (exit {rc})"
            else:
                return result.get('message', 'Done')
        else:
            return f"Failed: {result.get('message', 'Unknown error')}"

    def _build_continuation_prompt(self, ai_response: str, command_str: str, result: Dict, iteration: int = 0):
        """
        Build continuation prompt for recursive AI call after retrieval command.

        Returns:
            str or dict: For text commands, returns string prompt.
                        For file commands with images, returns dict with:
                        {"text": str, "content_blocks": list}
        """
        remaining = self.max_iterations - iteration - 1
        if remaining <= 1:
            iterations_note = f"\n(This is your last command iteration — wrap up your response.)"
        elif remaining < self.max_iterations:
            iterations_note = f"\n({remaining} command iterations remaining if needed.)"
        else:
            iterations_note = ""
        if result.get("success"):
            if result["command"] == "recall":
                memories = result.get("data", {}).get("results", [])
                result_text = "\n\n[Command Result: @recall]\n"
                result_text += f"Found {len(memories)} relevant memories:\n"
                for mem in memories[:5]:  # Show top 5
                    result_text += f"- [ID:{mem.get('id', '?')}] {mem.get('timestamp', 'Unknown time')}: {mem.get('content', '')[:100]}...\n"
                if len(memories) > 5:
                    result_text += f"(and {len(memories) - 5} more)\n"
            elif result["command"] == "review":
                messages = result.get("data", [])
                result_text = f"\n\n[Command Result: @review]\n"
                result_text += f"Found {len(messages)} messages in requested timeframe\n"
            elif result["command"] == "graph":
                result_text = f"\n\n[Command Result: @graph]\n{result.get('message', 'Success')}\n"
            elif result["command"] == "concept":
                result_text = f"\n\n[Command Result: @concept]\n{result.get('message', 'Success')}\n"
            elif result["command"] in ["file", "describe"]:
                # Phase 7: File viewing command - handle multimodal content
                data = result.get("data", {})

                # @file list / @file search — show listing and let AI continue
                if data.get("sub_command") in ("list", "search"):
                    result_text = f"\n\n[Command Result: {command_str}]\n"
                    result_text += data.get("content", result.get("message", ""))
                    result_text += "\n"
                    return f"""{ai_response}

{result_text}

IMPORTANT: You just received the file listing. Now CONTINUE your response naturally - use this information to decide your next action (e.g. @file view or @describe to inspect a specific file)."""

                filename = data.get("filename", "unknown")
                content_block = data.get("content_block")

                result_text = f"\n\n[Command Result: {command_str}]\n"
                result_text += f"File loaded: {filename}\n"

                description = data.get("description", "")
                if description:
                    result_text += f"Description: {description}\n"

                if data.get("needs_description"):
                    result_text += "\nPLEASE CREATE A DESCRIPTION for this file. After viewing it, use:\n"
                    result_text += f"@describe {data.get('file_uuid', '')[:8]} | Your 1-3 sentence description here\n"

                # Check if content is an image (multimodal)
                if content_block and content_block.get("type") == "image":
                    # Return dict with image for multimodal handling
                    continuation_instructions = """

IMPORTANT: You just received the file content. Now CONTINUE your response naturally - describe what you see in the file and respond to it appropriately."""

                    return {
                        "text": f"{ai_response}\n\n{result_text}\n{continuation_instructions}",
                        "content_blocks": [content_block],
                        "is_multimodal": True
                    }
                elif content_block and content_block.get("type") == "text":
                    # Text content - include in prompt
                    file_content = content_block.get("text", "")
                    if len(file_content) > 2000:
                        file_content = file_content[:2000] + "\n[Content truncated...]"
                    result_text += f"\nFile content:\n---\n{file_content}\n---\n"
            elif result["command"] == "help":
                result_text = f"\n\n[Command Result: @help]\n{result.get('message', '')}\n"
            elif result["command"] == "view":
                result_text = f"\n\n[Command Result: @view]\n{result.get('message', '')}\n"
            elif result["command"] == "run":
                data = result.get("data", {})
                output = data.get("output", "")
                errors = data.get("errors", "")
                rc = data.get("return_code", -1)
                result_text = f"\n\n[Command Result: @run (exit code {rc})]\n"
                if output:
                    result_text += f"{output}\n"
                if errors:
                    result_text += f"[stderr]\n{errors}\n"
                if not output and not errors:
                    result_text += "(no output)\n"

                # Build embeddable output for persistent storage in active context.
                # Stripped on tier transition to save tokens in long-term storage.
                embed_parts = []
                if output:
                    embed_parts.append(output.rstrip())
                if errors:
                    embed_parts.append(f"[stderr]\n{errors.rstrip()}")
                if embed_parts:
                    self._last_run_embed = f"\n\n[run output]\n{chr(10).join(embed_parts)}\n[/run output]"
                else:
                    self._last_run_embed = None
            else:
                result_text = f"\n\n[Command Result: {command_str}]\n{result.get('message', 'Success')}\n"
        else:
            result_text = f"\n\n[Command Result: {command_str}]\nFailed: {result.get('message', 'Unknown error')}\n"

        return f"""{ai_response}

{result_text}

IMPORTANT: You just received the results from your command. Now CONTINUE your response naturally - don't restate what you already said. Use the new information to ADD to your previous message, like continuing a conversation after checking your notes.{iterations_note}"""
