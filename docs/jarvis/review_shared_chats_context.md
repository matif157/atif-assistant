{
  "info": {
    "id": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
    "slug": "calm-wizard",
    "projectID": "904da824890530be11b79eda2dac381cb08a852f",
    "directory": "/Users/husayn/Documents/Default Project",
    "path": "Documents/Default Project",
    "summary": {
      "additions": 0,
      "deletions": 0,
      "files": 0
    },
    "cost": 0,
    "tokens": {
      "input": 2627659,
      "output": 341155,
      "reasoning": 8878,
      "cache": {
        "read": 33460672,
        "write": 0
      }
    },
    "share": {
      "url": "https://opncd.ai/share/u2VQ44ie"
    },
    "title": "Review shared chats for task context",
    "agent": "build",
    "model": {
      "id": "nemotron-3-ultra-free",
      "providerID": "opencode",
      "variant": "default"
    },
    "version": "1.18.31",
    "time": {
      "created": 1789949748230,
      "updated": 1789987505272
    }
  },
  "messages": [
    {
      "info": {
        "id": "msg_0c151a466001lKMIEWMTPw5QU9",
        "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
        "role": "user",
        "time": {
          "created": 1789949748379
        },
        "summary": {
          "diffs": []
        },
        "agent": "build",
        "model": {
          "providerID": "opencode",
          "modelID": "big-pickle"
        }
      },
      "parts": [
        {
          "id": "prt_0c151a467001W70gJ0qizD6aiB",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c151a466001lKMIEWMTPw5QU9",
          "type": "text",
          "text": "https://chatgpt.com/share/6ab076bf-499c-83ee-88c2-1cd242b45028 read it https://opncd.ai/share/OVAz7dda and this one and remembered all with focus on what you are gonna doing for me and just only include the mentioned file when need , "
        }
      ]
    },
    {
      "info": {
        "id": "msg_0c151a4a1001Yc9ISr3Y2XIoqf",
        "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
        "role": "assistant",
        "time": {
          "created": 1789949748385,
          "completed": 1789949781044
        },
        "parentID": "msg_0c151a466001lKMIEWMTPw5QU9",
        "modelID": "big-pickle",
        "providerID": "opencode",
        "mode": "build",
        "agent": "build",
        "path": {
          "cwd": "/Users/husayn/Documents/Default Project",
          "root": "/Users/husayn"
        },
        "cost": 0,
        "tokens": {
          "total": 8878,
          "input": 6897,
          "output": 189,
          "reasoning": 0,
          "cache": {
            "read": 1792,
            "write": 0
          }
        },
        "finish": "tool-calls"
      },
      "parts": [
        {
          "id": "prt_0c151ab15001uq6hvJeRZ13Rls",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c151a4a1001Yc9ISr3Y2XIoqf",
          "type": "step-start",
          "snapshot": "cb1bdb4c6b69e3675a41f50ac75f04390956165d"
        },
        {
          "id": "prt_0c151ab23001HMpTY4hoIfIDhF",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c151a4a1001Yc9ISr3Y2XIoqf",
          "type": "reasoning",
          "text": "The user is asking me to read two URLs:\n1. https://chatgpt.com/share/6ab076bf-499c-83ee-88c2-1cd242b45028\n2. https://opncd.ai/share/OVAz7dda\n\nLet me fetch these to understand what the user wants me to do.",
          "time": {
            "start": 1789949750051,
            "end": 1789949750524
          }
        },
        {
          "id": "prt_0c151acfd001jancCFRcaDdHny",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c151a4a1001Yc9ISr3Y2XIoqf",
          "type": "tool",
          "callID": "call_081538b137d04e608cc91fe4",
          "tool": "webfetch",
          "state": {
            "status": "error",
            "input": {
              "url": "https://chatgpt.com/share/6ab076bf-499c-83ee-88c2-1cd242b45028"
            },
            "error": "Request timed out",
            "time": {
              "start": 1789949750846,
              "end": 1789949780853
            }
          }
        },
        {
          "id": "prt_0c151ae4c001ccLSbFMG6HrQZw",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c151a4a1001Yc9ISr3Y2XIoqf",
          "type": "tool",
          "callID": "call_cbeb629fe75f4a779ea87894",
          "tool": "webfetch",
          "state": {
            "status": "error",
            "input": {
              "url": "https://opncd.ai/share/OVAz7dda"
            },
            "error": "Response too large (exceeds 5MB limit)",
            "time": {
              "start": 1789949750933,
              "end": 1789949754903
            }
          }
        },
        {
          "id": "prt_0c15223e5001bxTK54e8tAVQlk",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c151a4a1001Yc9ISr3Y2XIoqf",
          "type": "step-finish",
          "reason": "tool-calls",
          "snapshot": "cb1bdb4c6b69e3675a41f50ac75f04390956165d",
          "cost": 0,
          "tokens": {
            "total": 8878,
            "input": 6897,
            "output": 189,
            "reasoning": 0,
            "cache": {
              "read": 1792,
              "write": 0
            }
          }
        }
      ]
    },
    {
      "info": {
        "id": "msg_0c15224350015eDdKMPS67r1tB",
        "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
        "role": "assistant",
        "time": {
          "created": 1789949781045,
          "completed": 1789949787747
        },
        "parentID": "msg_0c151a466001lKMIEWMTPw5QU9",
        "modelID": "big-pickle",
        "providerID": "opencode",
        "mode": "build",
        "agent": "build",
        "path": {
          "cwd": "/Users/husayn/Documents/Default Project",
          "root": "/Users/husayn"
        },
        "cost": 0,
        "tokens": {
          "total": 9023,
          "input": 206,
          "output": 113,
          "reasoning": 0,
          "cache": {
            "read": 8704,
            "write": 0
          }
        },
        "finish": "tool-calls"
      },
      "parts": [
        {
          "id": "prt_0c1522bef001YRCab1y5UXJuXC",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c15224350015eDdKMPS67r1tB",
          "type": "step-start",
          "snapshot": "cb1bdb4c6b69e3675a41f50ac75f04390956165d"
        },
        {
          "id": "prt_0c1522bf3001sy1FLbuGr5GxMI",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c15224350015eDdKMPS67r1tB",
          "type": "reasoning",
          "text": "The first URL timed out and the second was too large. Let me try fetching them again with different approaches.",
          "time": {
            "start": 1789949783027,
            "end": 1789949783079
          }
        },
        {
          "id": "prt_0c1522c2b001t9xki4QIm9jaFR",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c15224350015eDdKMPS67r1tB",
          "type": "text",
          "text": "\n\n",
          "time": {
            "start": 1789949783083,
            "end": 1789949783318
          }
        },
        {
          "id": "prt_0c1522c4f0015JpjAvDgWgat0O",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c15224350015eDdKMPS67r1tB",
          "type": "tool",
          "callID": "call_6f6588b4be044f84a97e1679",
          "tool": "webfetch",
          "state": {
            "status": "completed",
            "input": {
              "url": "https://chatgpt.com/share/6ab076bf-499c-83ee-88c2-1cd242b45028",
              "timeout": 120
            },
            "output": "ChatGPT - Create CRM Theme",
            "title": "https://chatgpt.com/share/6ab076bf-499c-83ee-88c2-1cd242b45028 (text/html; charset=utf-8)",
            "metadata": {
              "truncated": false
            },
            "time": {
              "start": 1789949783287,
              "end": 1789949787573
            }
          }
        },
        {
          "id": "prt_0c1523e1b001Ae8Ly1kuTSGx6u",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c15224350015eDdKMPS67r1tB",
          "type": "step-finish",
          "reason": "tool-calls",
          "snapshot": "cb1bdb4c6b69e3675a41f50ac75f04390956165d",
          "cost": 0,
          "tokens": {
            "total": 9023,
            "input": 206,
            "output": 113,
            "reasoning": 0,
            "cache": {
              "read": 8704,
              "write": 0
            }
          }
        }
      ]
    },
    {
      "info": {
        "id": "msg_0c1523e65001y3EplyUYjvWj0n",
        "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
        "role": "assistant",
        "time": {
          "created": 1789949787749,
          "completed": 1789949793975
        },
        "parentID": "msg_0c151a466001lKMIEWMTPw5QU9",
        "modelID": "big-pickle",
        "providerID": "opencode",
        "mode": "build",
        "agent": "build",
        "path": {
          "cwd": "/Users/husayn/Documents/Default Project",
          "root": "/Users/husayn"
        },
        "cost": 0,
        "tokens": {
          "total": 9175,
          "input": 336,
          "output": 135,
          "reasoning": 0,
          "cache": {
            "read": 8704,
            "write": 0
          }
        },
        "finish": "tool-calls"
      },
      "parts": [
        {
          "id": "prt_0c1524490001odY0cXjR6JkMRl",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c1523e65001y3EplyUYjvWj0n",
          "type": "step-start",
          "snapshot": "cb1bdb4c6b69e3675a41f50ac75f04390956165d"
        },
        {
          "id": "prt_0c1524494001AMtb30Q39CAxmH",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c1523e65001y3EplyUYjvWj0n",
          "type": "reasoning",
          "text": "The ChatGPT share resulted in \"Create CRM Theme\" - that's title. Let me try again with a different format to get actual content.",
          "time": {
            "start": 1789949789332,
            "end": 1789949789517
          }
        },
        {
          "id": "prt_0c152454e001oHp5M014tL34F3",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c1523e65001y3EplyUYjvWj0n",
          "type": "tool",
          "callID": "call_7a387dee74024c12885fd8ff",
          "tool": "webfetch",
          "state": {
            "status": "completed",
            "input": {
              "format": "text",
              "timeout": 120,
              "url": "https://chatgpt.com/share/6ab076bf-499c-83ee-88c2-1cd242b45028"
            },
            "output": "ChatGPT - Create CRM Theme",
            "title": "https://chatgpt.com/share/6ab076bf-499c-83ee-88c2-1cd242b45028 (text/html; charset=utf-8)",
            "metadata": {
              "truncated": false
            },
            "time": {
              "start": 1789949789766,
              "end": 1789949793826
            }
          }
        },
        {
          "id": "prt_0c152566e001148HEf5NISthMs",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c1523e65001y3EplyUYjvWj0n",
          "type": "step-finish",
          "reason": "tool-calls",
          "snapshot": "cb1bdb4c6b69e3675a41f50ac75f04390956165d",
          "cost": 0,
          "tokens": {
            "total": 9175,
            "input": 336,
            "output": 135,
            "reasoning": 0,
            "cache": {
              "read": 8704,
              "write": 0
            }
          }
        }
      ]
    },
    {
      "info": {
        "id": "msg_0c15256b9001yr9DEHTvM69N0L",
        "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
        "role": "assistant",
        "time": {
          "created": 1789949793977,
          "completed": 1789949800206
        },
        "parentID": "msg_0c151a466001lKMIEWMTPw5QU9",
        "modelID": "big-pickle",
        "providerID": "opencode",
        "mode": "build",
        "agent": "build",
        "path": {
          "cwd": "/Users/husayn/Documents/Default Project",
          "root": "/Users/husayn"
        },
        "cost": 0,
        "tokens": {
          "total": 9430,
          "input": 232,
          "output": 238,
          "reasoning": 0,
          "cache": {
            "read": 8960,
            "write": 0
          }
        },
        "finish": "tool-calls"
      },
      "parts": [
        {
          "id": "prt_0c1525d1a001kJTY55OM9G7FCo",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c15256b9001yr9DEHTvM69N0L",
          "type": "step-start",
          "snapshot": "cb1bdb4c6b69e3675a41f50ac75f04390956165d"
        },
        {
          "id": "prt_0c1525d20001F1CAe5JyVGmFeb",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c15256b9001yr9DEHTvM69N0L",
          "type": "reasoning",
          "text": "The ChatGPT share returns just the title, not the content. It seems the full content requires JavaScript rendering. Let me try the second link again, maybe with a format. But it was too large (>5MB). Let me try to fetch it and see if it can be summarized, or maybe I should use a different tool.\n\nFor ChatGPT shares, they're rendered client-side. Let me try the opencode share URL in text format, maybe it'll be smaller.\n\nActually the second link https://opncd.ai/share/OVAz7dda returned \"Response too large (exceeds 5MB limit)\". This is likely a long conversation about what the user wants me to do. Let me try fetching with text format.",
          "time": {
            "start": 1789949795616,
            "end": 1789949796397
          }
        },
        {
          "id": "prt_0c15260300019YBbr6zaxasibf",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c15256b9001yr9DEHTvM69N0L",
          "type": "tool",
          "callID": "call_47f228552ac248b98da3adcd",
          "tool": "webfetch",
          "state": {
            "status": "error",
            "input": {
              "format": "text",
              "timeout": 120,
              "url": "https://opncd.ai/share/OVAz7dda"
            },
            "error": "Response too large (exceeds 5MB limit)",
            "time": {
              "start": 1789949796546,
              "end": 1789949800021
            }
          }
        },
        {
          "id": "prt_0c1526ec3001IQoquDnmZDzdY4",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c15256b9001yr9DEHTvM69N0L",
          "type": "step-finish",
          "reason": "tool-calls",
          "snapshot": "cb1bdb4c6b69e3675a41f50ac75f04390956165d",
          "cost": 0,
          "tokens": {
            "total": 9430,
            "input": 232,
            "output": 238,
            "reasoning": 0,
            "cache": {
              "read": 8960,
              "write": 0
            }
          }
        }
      ]
    },
    {
      "info": {
        "id": "msg_0c1526f10001HwrI0GQGcoyzup",
        "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
        "role": "assistant",
        "time": {
          "created": 1789949800208,
          "completed": 1789949811096
        },
        "parentID": "msg_0c151a466001lKMIEWMTPw5QU9",
        "modelID": "big-pickle",
        "providerID": "opencode",
        "mode": "build",
        "agent": "build",
        "path": {
          "cwd": "/Users/husayn/Documents/Default Project",
          "root": "/Users/husayn"
        },
        "cost": 0,
        "tokens": {
          "total": 9828,
          "input": 235,
          "output": 377,
          "reasoning": 0,
          "cache": {
            "read": 9216,
            "write": 0
          }
        },
        "finish": "tool-calls"
      },
      "parts": [
        {
          "id": "prt_0c1527256001uctE97HzTVD3SY",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c1526f10001HwrI0GQGcoyzup",
          "type": "step-start",
          "snapshot": "cb1bdb4c6b69e3675a41f50ac75f04390956165d"
        },
        {
          "id": "prt_0c1527258001f7xXqhmmI9nI07",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c1526f10001HwrI0GQGcoyzup",
          "type": "reasoning",
          "text": "Both URLs are not fully readable. The first one returns just the title \"Create CRM Theme\" and the second one is too large (5MB+). Let me try to use curl to fetch the raw content, maybe the opncd.ai share has an API endpoint. Let me try using bash with curl to get the raw data.",
          "time": {
            "start": 1789949801048,
            "end": 1789949801426
          }
        },
        {
          "id": "prt_0c15273d5001CiDLvYG8Ii2Nwf",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c1526f10001HwrI0GQGcoyzup",
          "type": "tool",
          "callID": "call_a7a72c468a3c4505983b653f",
          "tool": "bash",
          "state": {
            "status": "completed",
            "input": {
              "command": "curl -sL --max-time 60 \"https://opncd.ai/share/OVAz7dda\" -o /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_ovaz7dda.html && wc -c /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_ovaz7dda.html"
            },
            "output": " 8508668 /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_ovaz7dda.html\n",
            "title": "curl -sL --max-time 60 \"https://opncd.ai/share/OVAz7dda\" -o /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_ovaz7dda.html && wc -c /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_ovaz7dda.html",
            "metadata": {
              "output": " 8508668 /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_ovaz7dda.html\n",
              "exit": 0,
              "truncated": false
            },
            "time": {
              "start": 1789949801899,
              "end": 1789949810216
            }
          }
        },
        {
          "id": "prt_0c15275b2001lxisT3KGXZcg5R",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c1526f10001HwrI0GQGcoyzup",
          "type": "tool",
          "callID": "call_6bce7a8521f540e7b1fcb25f",
          "tool": "bash",
          "state": {
            "status": "completed",
            "input": {
              "command": "curl -sL --max-time 60 \"https://chatgpt.com/share/6ab076bf-499c-83ee-88c2-1cd242b45028\" -o /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_chatgpt.html && wc -c /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_chatgpt.html"
            },
            "output": " 3493306 /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_chatgpt.html\n",
            "title": "curl -sL --max-time 60 \"https://chatgpt.com/share/6ab076bf-499c-83ee-88c2-1cd242b45028\" -o /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_chatgpt.html && wc -c /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_chatgpt.html",
            "metadata": {
              "output": " 3493306 /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_chatgpt.html\n",
              "exit": 0,
              "truncated": false
            },
            "time": {
              "start": 1789949802161,
              "end": 1789949810912
            }
          }
        },
        {
          "id": "prt_0c1529949001HkKYMNAufPxCCm",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c1526f10001HwrI0GQGcoyzup",
          "type": "step-finish",
          "reason": "tool-calls",
          "snapshot": "cb1bdb4c6b69e3675a41f50ac75f04390956165d",
          "cost": 0,
          "tokens": {
            "total": 9828,
            "input": 235,
            "output": 377,
            "reasoning": 0,
            "cache": {
              "read": 9216,
              "write": 0
            }
          }
        }
      ]
    },
    {
      "info": {
        "id": "msg_0c1529999001LnCNg9SKyfowax",
        "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
        "role": "assistant",
        "time": {
          "created": 1789949811097,
          "completed": 1789949817375
        },
        "parentID": "msg_0c151a466001lKMIEWMTPw5QU9",
        "modelID": "big-pickle",
        "providerID": "opencode",
        "mode": "build",
        "agent": "build",
        "path": {
          "cwd": "/Users/husayn/Documents/Default Project",
          "root": "/Users/husayn"
        },
        "cost": 0,
        "tokens": {
          "total": 10162,
          "input": 209,
          "output": 225,
          "reasoning": 0,
          "cache": {
            "read": 9728,
            "write": 0
          }
        },
        "finish": "tool-calls"
      },
      "parts": [
        {
          "id": "prt_0c152a04f001O4qGW5Skf6Hcas",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c1529999001LnCNg9SKyfowax",
          "type": "step-start",
          "snapshot": "cb1bdb4c6b69e3675a41f50ac75f04390956165d"
        },
        {
          "id": "prt_0c152a051001HLd4Ot8bdKCeUA",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c1529999001LnCNg9SKyfowax",
          "type": "reasoning",
          "text": "Both files downloaded. Now let me look at their content. The ChatGPT one is 3.4MB and the opencode one is 8.5MB. Let me examine them structure. First, let me check what interesting text is in them. Let me use grep to find key content.\n\nThe ChatGPT shared link content is client-side rendered typically, but maybe the HTML contains the JSON data. Let me search for the meaningful text content.",
          "time": {
            "start": 1789949812817,
            "end": 1789949815173
          }
        },
        {
          "id": "prt_0c152a989001KzJxg2kVJDQVzZ",
          "sessionID": "ses_f3eae5bfaffeYNqVNEu2VQ44ie",
          "messageID": "msg_0c1529999001LnCNg9SKyfowax",
          "type": "tool",
          "callID": "call_938b1d4d2dc64ae4a141741e",
          "tool": "bash",
          "state": {
            "status": "completed",
            "input": {
              "command": "file /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_chatgpt.html && strings /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_chatgpt.html | grep -i -m 20 \"crm\""
            },
            "output": "...output truncated...\n\nFull output saved to: /Users/husayn/.local/share/opencode/tool-output/tool_0c152b16a001rl1TPo1tHkeFDp\n\n Malaysia\\\\n\\\\nYou do a 3-year computing degree.\\\\n\\\\nDuring those three years:\\\\n\\\\n**CGPA high + English + programming + GitHub + internships + CRM projects + professional networking**\\\\n\\\\nThen:\\\\n\\\\n### Stage 2\\\\nMalaysia \n Pakistan\\\\n\\\\nYou have:\\\\n\\\\n**51% Intermediate**\\\\n\\\\n**2024 completion**\\\\n\\\\n**limited money**\\\\n\\\\n**growing CRM/software experience**\\\\n\\\\nYou need to improve academically and professionally.\\\\n\\\\n\n backend\\\\n\\\\nBy Year 3:\\\\n\\\\nCRM architecture \n\\\\n\\\\n---\\\\n\\\\n# 18. My current judgement of Malaysia for YOU\\\\n\\\\n### As a permanent destination:\\\\n\\\\n**5/10**\\\\n\\\\nI don't love it for you.\\\\n\\\\n### As a cheap English-language education platform:\\\\n\\\\n**7/10**\\\\n\\\\nPotentially useful.\\\\n\\\\n### As a path to Singapore:\\\\n\\\\n**5/10**\\\\n\\\\nPossible, but highly competitive.\\\\n\\\\n### As a path to a European master's:\\\\n\\\\n**8/10 IF we choose the university carefully**\\\\n\\\\nThis is where I become much more positive.\\\\n\\\\n### As a path relying heavily on part-time jobs:\\\\n\\\\n**3/10**\\\\n\\\\nI would not approve this plan for my son.\\\\n\\\\n### As a path for your long-term IT/CRM career:\\\\n\\\\n**7/10**, provided you use Malaysia to build your profile rather than waiting for Malaysia to give you a job.\\\\n\\\\n---\\\\n\\\\n# The biggest discovery from this research\\\\n\\\\nI actually think your question has uncovered a **potentially better strategy than our original country ranking**.\\\\n\\\\nInstead of asking:\\\\n\\\\n\\u003e **Italy or Romania or Malaysia?**\\\\n\\\\nwe should ask:\\\\n\\\\n## \n Build yourself\\\\n\\\\nDuring the degree:\\\\n\\\\n**Italian/German/another European language + internships + GitHub + CRM/software portfolio + local work experience + networking + European CV**\\\\n\\\\nYour biggest objective isn't earning \n Finland  \\\\netc.\\\\n\\\\nYou would be applying as:\\\\n\\\\n\\u003e **European-educated software/CRM professional with local experience**\\\\n\\\\nrather than:\\\\n\\\\n\\u003e **Pakistani student with 51% Intermediate looking for sponsorship from abroad.**\\\\n\\\\nThat is an enormous difference.\\\\n\\\\n---\\\\n\\\\n# \n\\\\n\\\\nThat's unusually attractive.\\\\n\\\\nAnd for someone pursuing:\\\\n\\\\n**software + automation + SaaS + CRM + digital business**\\\\n\\\\nthe country itself is conceptually a very good fit.\\\\n\\\\nBut here's the catch:\\\\n\\\\n**Estonia is not automatically a cheap country.**\\\\n\\\\nYour 18 lakh budget makes the financial side much more important than the technology ecosystem.\\\\n\\\\nSo I would investigate Estonia **only if we find a genuinely affordable programme and realistic financing**.\\\\n\\\\n---\\\\n\\\\n# \n\\\\n\\\\nFor your career:\\\\n\\\\n**CRM + software + automation + backend + business systems**\\\\n\\\\nGermany makes much more sense as a long-term target than Malaysia.\\\\n\\\\nBut you currently don't have the financial strength to treat Germany casually.\\\\n\\\\nSo I'd rather get you **into Europe safely first** than force Germany prematurely.\\\\n\\\\n---\\\\n\\\\n# \n pathway that some European countries provide.\\\\n\\\\nMalaysia isn't bad.\\\\n\\\\n**It is simply less aligned with your objective.**\\\\n\\\\n---\\\\n\\\\n# One HUGE misconception I want you to avoid\\\\n\\\\nSuppose you are studying in Romania.\\\\n\\\\nYou get a beautiful job advertisement:\\\\n\\\\n\\u003e **PHP/CRM Developer \n CRM/software internship \n\\\\n\\\\nThat fits your existing direction in **PHP, CRM, business software and automation** better linguistically than Romania might.\\\\n\\\\nBut there is a second problem:\\\\n\\\\n### Staying in Malaysia after graduation\\\\n\\\\nMalaysia does have a **Graduate Pass**, but the current government eligibility list is nationality-specific, and **Pakistan is not on the current eligible-country list** shown by Education Malaysia. \n\\\\n\\\\nSo my rule for you would be:\\\\n\\\\n\\u003e **Italy only works as a career strategy if you learn Italian seriously and build a strong technical career while studying.**\\\\n\\\\nFor your CRM/software ambitions, that means you should not arrive in Italy intending to remain an ordinary part-time worker. You should be building toward **software developer / CRM / business systems / automation roles**.\\\\n\\\\n---\\\\n\\\\n# Italy has one Pakistan-specific problem right now\\\\n\\\\nThis is important because you are from Faisalabad.\\\\n\\\\nAs of September 2026, the Italian Embassy in Pakistan has **permanently closed the Faisalabad and Multan visa application centres**. Applications are now handled through Lahore and Islamabad. \n\\\\n\\\\nThat is better than Malaysia for somebody hoping to use work to reduce expenses.\\\\n\\\\nBut I don't want to sell Romania as something it isn't.\\\\n\\\\nFor your long-term goal of becoming a **high-end software/CRM/business-systems professional and eventually building a company**, I would personally rather see you move toward the stronger European tech economies after building yourself up.\\\\n\\\\nRomania could be a **stepping-stone**, but I would not automatically call it your final destination.\\\\n\\\\n---\\\\n\\\\n# Poland has become more complicated\\\\n\\\\nPoland used to be one of the obvious recommendations for affordable European study.\\\\n\\\\nIt still has advantages.\\\\n\\\\nOfficial Polish guidance says many international students can work without a separate work permit while studying full-time. \n5,570 of total risk capital**.\\\\n\\\\nThat is very different.\\\\n\\\\nAnd the first months are the dangerous part because you have **zero guarantee that you will get a job quickly**.\\\\n\\\\n---\\\\n\\\\n# There is another issue I am more worried about: 51% Intermediate\\\\n\\\\nI don't want to pretend this doesn't matter.\\\\n\\\\n51% is not the profile I would normally build an aggressive international bachelor's plan around.\\\\n\\\\nBut your situation has one important positive:\\\\n\\\\n**you have already spent the period after Intermediate building real work experience.**\\\\n\\\\nYou completed Intermediate in 2024 and you've been moving into actual business/CRM/software work rather than doing nothing.\\\\n\\\\nThat means the gap can potentially be explained.\\\\n\\\\nFor your long-term career, that work experience could become much more valuable than you realize \n Italy\\\\n\\\\nTarget **English-taught bachelor's programmes related to Computer Science / Information Systems / Business Information Systems / Software / Economics + technology**, depending on what your Intermediate subjects allow.\\\\n\\\\nSimultaneously target regional scholarships.\\\\n\\\\nLearn Italian from Pakistan.\\\\n\\\\nBuild your programming/CRM portfolio aggressively.\\\\n\\\\nApply yourself wherever possible rather than paying a consultant to \n4 years doing:\\\\n\\\\n**BS in Pakistan + serious software development + CRM work + GitHub + English + German/Italian + savings**\\\\n\\\\nand then apply for a master's in Europe.\\\\n\\\\nYour situation changes dramatically.\\\\n\\\\nInstead of:\\\\n\\\\n**51% Intermediate \n CRM/software experience \n much stronger employment prospects**\\\\n\\\\nFor someone whose actual career direction is already **CRM \\u0026 Business Software Development**, I think this deserves extremely serious consideration.\\\\n\\\\nIt could actually get you to Europe **with much less financial risk**.\\\\n\\\\n---\\\\n\\\\n# My current decision\\\\n\\\\nSo, at this stage, my father-style decision is:\\\\n\\\\n\\u003e **Do not gamble the entire PKR 18 lakh on a normal self-funded European bachelor's.**\\\\n\\\\n\\u003e **Make Italy your primary scholarship/low-cost target, Hungary your scholarship alternative, Romania a backup, and Germany your longer-term career target.**\\\\n\\\\nAnd most importantly:\\\\n\\\\n\\u003e **Do not make \n",
            "title": "file /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_chatgpt.html && strings /var/folders/q9/1lwbyfks77b_bzmk3jz1j91h0000gn/T/opencode/share_chatgpt.html | grep -i -m 20 \"crm\"",
            "metadata": {
              "output": "...\n\n\":14800,\\\"_636\\\":14815,\\\"_638\\\":14816,\\\"_640\\\":14817},{\\\"_635\\\":14714,\\\"_636\\\":14799,\\\"_638\\\":14800,\\\"_640\\\":14801},{\\\"_635\\\":14715,\\\"_636\\\":14788,\\\"_638\\\":14714,\\\"_640\\\":14789},{\\\"_635\\\":14716,\\\"_636\\\":14778,\\\"_638\\\":14715,\\\"_640\\\":14779},{\\\"_635\\\":14702,\\\"_636\\\":14767,\\\"_638\\\":14716,\\\"_640\\\":14768},{\\\"_635\\\":14691,\\\"_636\\\":14701,\\\"_638\\\":14702,\\\"_640\\\":14703},{\\\"_635\\\":14482,\\\"_636\\\":14690,\\\"_638\\\":14691,\\\"_640\\\":14692},{\\\"_635\\\":14446,\\\"_636\\\":14481,\\\"_638\\\":14482,\\\"_640\\\":14483},{\\\"_635\\\":14427,\\\"_636\\\":14445,\\\"_638\\\":14446,\\\"_640\\\":14447},{\\\"_635\\\":14411,\\\"_636\\\":14426,\\\"_638\\\":14427,\\\"_640\\\":14428},{\\\"_635\\\":14395,\\\"_636\\\":14410,\\\"_638\\\":14411,\\\"_640\\\":14412},{\\\"_635\\\":14284,\\\"_636\\\":14394,\\\"_638\\\":14395,\\\"_640\\\":14396},{\\\"_635\\\":14285,\\\"_636\\\":14382,\\\"_638\\\":14284,\\\"_640\\\":14383},{\\\"_635\\\":14258,\\\"_636\\\":14371,\\\"_638\\\":14285,\\\"_640\\\":14372},{\\\"_635\\\":14247,\\\"_636\\\":14257,\\\"_638\\\":14258,\\\"_640\\\":14259},{\\\"_635\\\":13828,\\\"_636\\\":14246,\\\"_638\\\":14247,\\\"_640\\\":14248},{\\\"_635\\\":13814,\\\"_636\\\":13827,\\\"_638\\\":13828,\\\"_640\\\":13829},{\\\"_635\\\":13797,\\\"_636\\\":13813,\\\"_638\\\":13814,\\\"_640\\\":13815},{\\\"_635\\\":13780,\\\"_636\\\":13796,\\\"_638\\\":13797,\\\"_640\\\":13798},{\\\"_635\\\":13771,\\\"_636\\\":13787,\\\"_638\\\":13780,\\\"_640\\\":13788},{\\\"_635\\\":13760,\\\"_636\\\":13770,\\\"_638\\\":13771,\\\"_640\\\":13772},{\\\"_635\\\":13721,\\\"_636\\\":13759,\\\"_638\\\":13760,\\\"_640\\\":13761},{\\\"_635\\\":13707,\\\"_636\\\":13720,\\\"_638\\\":13721,\\\"_640\\\":13722},{\\\"_635\\\":13698,\\\"_636\\\":13706,\\\"_638\\\":13707,\\\"_640\\\":13708},{\\\"_635\\\":13689,\\\"_636\\\":13697,\\\"_638\\\":13698,\\\"_640\\\":13699},{\\\"_635\\\":13680,\\\"_636\\\":13688,\\\"_638\\\":13689,\\\"_640\\\":13690},{\\\"_635\\\":13672,\\\"_636\\\":13679,\\\"_638\\\":13680,\\\"_640\\\":13681},{\\\"_635\\\":13656,\\\"_636\\\":13671,\\\"_638\\\":13672,\\\"_640\\\":13673},{\\\"_635\\\":13571,\\\"_636\\\":13655,\\\"_638\\\":13656,\\\"_640\\\":13657},{\\\"_635\\\":13572,\\\"_636\\\":13641,\\\"_638\\\":13571,\\\"_640\\\":13642},{\\\"_635\\\":13559,\\\"_636\\\":13631,\\\"_638\\\":13572,\\\"_640\\\":13632},{\\\"_635\\\":13544,\\\"_636\\\":13558,\\\"_638\\\":13559,\\\"_640\\\":13560},{\\\"_635\\\":13527,\\\"_636\\\":13543,\\\"_638\\\":13544,\\\"_640\\\":13545},{\\\"_635\\\":13517,\\\"_636\\\":13534,\\\"_638\\\":13527,\\\"_640\\\":13535},{\\\"_635\\\":13502,\\\"_636\\\":13516,\\\"_638\\\":13517,\\\"_640\\\":13518},{\\\"_635\\\":13412,\\\"_636\\\":13501,\\\"_638\\\":13502,\\\"_640\\\":13503},{\\\"_635\\\":13413,\\\"_636\\\":13491,\\\"_638\\\":13412,\\\"_640\\\":13492},{\\\"_635\\\":13414,\\\"_636\\\":13481,\\\"_638\\\":13413,\\\"_640\\\":13482},{\\\"_635\\\":13400,\\\"_636\\\":13461,\\\"_638\\\":13414,\\\"_640\\\":13462},{\\\"_635\\\":13384,\\\"_636\\\":13399,\\\"_638\\\":13400,\\\"_640\\\":13401},{\\\"_635\\\":13229,\\\"_636\\\":13383,\\\"_638\\\":13384,\\\"_640\\\":13385},{\\\"_635\\\":13230,\\\"_636\\\":13374,\\\"_638\\\":13229,\\\"_640\\\":13375},{\\\"_635\\\":13351,\\\"_636\\\":13360,\\\"_638\\\":13230,\\\"_640\\\":13361},{\\\"_635\\\":13341,\\\"_636\\\":13350,\\\"_638\\\":13351,\\\"_640\\\":13352},{\\\"_635\\\":13331,\\\"_636\\\":13340,\\\"_638\\\":13341,\\\"_640\\\":13342},{\\\"_635\\\":13310,\\\"_636\\\":13330,\\\"_638\\\":13331,\\\"_640\\\":13332},{\\\"_635\\\":13293,\\\"_636\\\":13309,\\\"_638\\\":13310,\\\"_640\\\":13311},{\\\"_635\\\":13231,\\\"_636\\\":13292,\\\"_638\\\":13293,\\\"_640\\\":13294},{\\\"_635\\\":13274,\\\"_636\\\":13283,\\\"_638\\\":13231,\\\"_640\\\":13284},{\\\"_635\\\":13264,\\\"_636\\\":13273,\\\"_638\\\":13274,\\\"_640\\\":13275},{\\\"_635\\\":13249,\\\"_636\\\":13263,\\\"_638\\\":13264,\\\"_640\\\":13265},{\\\"_635\\\":13239,\\\"_636\\\":13248,\\\"_638\\\":13249,\\\"_640\\\":13250},{\\\"_635\\\":13220,\\\"_636\\\":13238,\\\"_638\\\":13239,\\\"_640\\\":13240},{\\\"_635\\\":13209,\\\"_636\\\":13219,\\\"_638\\\":13220,\\\"_640\\\":13221},{\\\"_635\\\":12658,\\\"_636\\\":13208,\\\"_638\\\":13209,\\\"_640\\\":13210},{\\\"_635\\\":12644,\\\"_636\\\":12657,\\\"_638\\\":12658,\\\"_640\\\":12659},{\\\"_635\\\":12628,\\\"_636\\\":12643,\\\"_638\\\":12644,\\\"_640\\\":12645},{\\\"_635\\\":12562,\\\"_636\\\":12627,\\\"_638\\\":12628,\\\"_640\\\":12629},{\\\"_635\\\":12563,\\\"_636\\\":12618,\\\"_638\\\":12562,\\\"_640\\\":12619},{\\\"_635\\\":12551,\\\"_636\\\":12608,\\\"_638\\\":12563,\\\"_640\\\":12609},{\\\"_635\\\":12536,\\\"_636\\\":12550,\\\"_638\\\":12551,\\\"_640\\\":12552},{\\\"_635\\\":12481,\\\"_636\\\":12535,\\\"_638\\\":12536,\\\"_640\\\":12537},{\\\"_635\\\":12482,\\\"_636\\\":12526,\\\"_638\\\":12481,\\\"_640\\\":12527},{\\\"_635\\\":12499,\\\"_636\\\":12507,\\\"_638\\\":12482,\\\"_640\\\":12508},{\\\"_635\\\":12490,\\\"_636\\\":12498,\\\"_638\\\":12499,\\\"_640\\\":12500},{\\\"_635\\\":12471,\\\"_636\\\":12489,\\\"_638\\\":12490,\\\"_640\\\":12491},{\\\"_635\\\":12456,\\\"_636\\\":12470,\\\"_638\\\":12471,\\\"_640\\\":12472},{\\\"_635\\\":12379,\\\"_636\\\":12455,\\\"_638\\\":12456,\\\"_640\\\":12457},{\\\"_635\\\":12380,\\\"_636\\\":12446,\\\"_638\\\":12379,\\\"_640\\\":12447},{\\\"_635\\\":12365,\\\"_636\\\":12436,\\\"_638\\\":12380,\\\"_640\\\":12437},{\\\"_635\\\":12356,\\\"_636\\\":12364,\\\"_638\\\":12365,\\\"_640\\\":12366},{\\\"_635\\\":12222,\\\"_636\\\":12355,\\\"_638\\\":12356,\\\"_640\\\":12357},{\\\"_635\\\":12337,\\\"_636\\\":12346,\\\"_638\\\":12222,\\\"_640\\\":12347},{\\\"_635\\\":9957,\\\"_636\\\":12336,\\\"_638\\\":12337,\\\"_640\\\":12338},{\\\"_635\\\":12318,\\\"_636\\\":12327,\\\"_638\\\":9957,\\\"_640\\\":12328},{\\\"_635\\\":12308,\\\"_636\\\":12317,\\\"_638\\\":12318,\\\"_640\\\":12319},{\\\"_635\\\":12298,\\\"_636\\\":12307,\\\"_638\\\":12308,\\\"_640\\\":12309},{\\\"_635\\\":12288,\\\"_636\\\":12297,\\\"_638\\\":12298,\\\"_640\\\":12299},{\\\"_635\\\":12278,\\\"_636\\\":12287,\\\"_638\\\":12288,\\\"_640\\\":12289},{\\\"_635\\\":12268,\\\"_636\\\":12277,\\\"_638\\\":12278,\\\"_640\\\":12279},{\\\"_635\\\":12258,\\\"_636\\\":12267,\\\"_638\\\":12268,\\\"_640\\\":12269},{\\\"_635\\\":12247,\\\"_636\\\":12257,\\\"_638\\\":12258,\\\"_640\\\":12259},{\\\"_635\\\":12230,\\\"_636\\\":12246,\\\"_638\\\":12247,\\\"_640\\\":12248},{\\\"_635\\\":12210,\\\"_636\\\":12229,\\\"_638\\\":12230,\\\"_640\\\":12231},{\\\"_635\\\":12194,\\\"_636\\\":12209,\\\"_638\\\":12210,\\\"_640\\\":12211},{\\\"_635\\\":12117,\\\"_636\\\":12193,\\\"_638\\\":12194,\\\"_640\\\":12195},{\\\"_635\\\":12118,\\\"_636\\\":12185,\\\"_638\\\":12117,\\\"_640\\\":12186},{\\\"_635\\\":12163,\\\"_636\\\":12172,\\\"_638\\\":12118,\\\"_640\\\":12173},{\\\"_635\\\":12153,\\\"_636\\\":12162,\\\"_638\\\":12163,\\\"_640\\\":12164},{\\\"_635\\\":12143,\\\"_636\\\":12152,\\\"_638\\\":12153,\\\"_640\\\":12154},{\\\"_635\\\":12126,\\\"_636\\\":12142,\\\"_638\\\":12143,\\\"_640\\\":12144},{\\\"_635\\\":12108,\\\"_636\\\":12125,\\\"_638\\\":12126,\\\"_640\\\":12127},{\\\"_635\\\":12097,\\\"_636\\\":12107,\\\"_638\\\":12108,\\\"_640\\\":12109},{\\\"_635\\\":11655,\\\"_636\\\":12096,\\\"_638\\\":12097,\\\"_640\\\":12098},{\\\"_635\\\":11641,\\\"_636\\\":11654,\\\"_638\\\":11655,\\\"_640\\\":11656},{\\\"_635\\\":11625,\\\"_636\\\":11640,\\\"_638\\\":11641,\\\"_640\\\":11642},{\\\"_635\\\":11564,\\\"_636\\\":11624,\\\"_638\\\":11625,\\\"_640\\\":11626},{\\\"_635\\\":11565,\\\"_636\\\":11615,\\\"_638\\\":11564,\\\"_640\\\":11616},{\\\"_635\\\":11553,\\\"_636\\\":11604,\\\"_638\\\":11565,\\\"_640\\\":11605},{\\\"_635\\\":11537,\\\"_636\\\":11552,\\\"_638\\\":11553,\\\"_640\\\":11554},{\\\"_635\\\":11520,\\\"_636\\\":11536,\\\"_638\\\":11537,\\\"_640\\\":11538},{\\\"_635\\\":11510,\\\"_636\\\":11527,\\\"_638\\\":11520,\\\"_640\\\":11528},{\\\"_635\\\":11495,\\\"_636\\\":11509,\\\"_638\\\":11510,\\\"_640\\\":11511},{\\\"_635\\\":11409,\\\"_636\\\":11494,\\\"_638\\\":11495,\\\"_640\\\":11496},{\\\"_635\\\":11410,\\\"_636\\\":11485,\\\"_638\\\":11409,\\\"_640\\\":11486},{\\\"_635\\\":11411,\\\"_636\\\":11474,\\\"_638\\\":11410,\\\"_640\\\":11475},{\\\"_635\\\":11398,\\\"_636\\\":11454,\\\"_638\\\":11411,\\\"_640\\\":11455},{\\\"_635\\\":11382,\\\"_636\\\":11397,\\\"_638\\\":11398,\\\"_640\\\":11399},{\\\"_635\\\":11320,\\\"_636\\\":11381,\\\"_638\\\":11382,\\\"_640\\\":11383},{\\\"_635\\\":11321,\\\"_636\\\":11372,\\\"_638\\\":11320,\\\"_640\\\":11373},{\\\"_635\\\":11349,\\\"_636\\\":11358,\\\"_638\\\":11321,\\\"_640\\\":11359},{\\\"_635\\\":11339,\\\"_636\\\":11348,\\\"_638\\\":11349,\\\"_640\\\":11350},{\\\"_635\\\":11329,\\\"_636\\\":11338,\\\"_638\\\":11339,\\\"_640\\\":11340},{\\\"_635\\\":11310,\\\"_636\\\":11328,\\\"_638\\\":11329,\\\"_640\\\":11330},{\\\"_635\\\":11295,\\\"_636\\\":11309,\\\"_638\\\":11310,\\\"_640\\\":11311},{\\\"_635\\\":11190,\\\"_636\\\":11294,\\\"_638\\\":11295,\\\"_640\\\":11296},{\\\"_635\\\":11191,\\\"_636\\\":11275,\\\"_638\\\":11190,\\\"_640\\\":11276},{\\\"_635\\\":11192,\\\"_636\\\":11264,\\\"_638\\\":11191,\\\"_640\\\":11265},{\\\"_635\\\":11178,\\\"_636\\\":11241,\\\"_638\\\":11192,\\\"_640\\\":11242},{\\\"_635\\\":11162,\\\"_636\\\":11177,\\\"_638\\\":11178,\\\"_640\\\":11179},{\\\"_635\\\":11107,\\\"_636\\\":11161,\\\"_638\\\":11162,\\\"_640\\\":11163},{\\\"_635\\\":11108,\\\"_636\\\":11153,\\\"_638\\\":11107,\\\"_640\\\":11154},{\\\"_635\\\":11127,\\\"_636\\\":11137,\\\"_638\\\":11108,\\\"_640\\\":11138},{\\\"_635\\\":11116,\\\"_636\\\":11126,\\\"_638\\\":11127,\\\"_640\\\":11128},{\\\"_635\\\":11095,\\\"_636\\\":11115,\\\"_638\\\":11116,\\\"_640\\\":11117},{\\\"_635\\\":11083,\\\"_636\\\":11094,\\\"_638\\\":11095,\\\"_640\\\":11096},{\\\"_635\\\":9895,\\\"_636\\\":11082,\\\"_638\\\":11083,\\\"_640\\\":11084},{\\\"_635\\\":9882,\\\"_636\\\":9894,\\\"_638\\\":9895,\\\"_640\\\":9896},{\\\"_635\\\":9873,\\\"_636\\\":9881,\\\"_638\\\":9882,\\\"_640\\\":9883},{\\\"_635\\\":9864,\\\"_636\\\":9872,\\\"_638\\\":9873,\\\"_640\\\":9874},{\\\"_635\\\":9855,\\\"_636\\\":9863,\\\"_638\\\":9864,\\\"_640\\\":9865},{\\\"_635\\\":9843,\\\"_636\\\":9854,\\\"_638\\\":9855,\\\"_640\\\":9856},{\\\"_635\\\":9829,\\\"_636\\\":9842,\\\"_638\\\":9843,\\\"_640\\\":9844},{\\\"_635\\\":9787,\\\"_636\\\":9828,\\\"_638\\\":9829,\\\"_640\\\":9830},{\\\"_635\\\":9805,\\\"_636\\\":9814,\\\"_638\\\":9787,\\\"_640\\\":9815},{\\\"_635\\\":9788,\\\"_636\\\":9804,\\\"_638\\\":9805,\\\"_640\\\":9806},{\\\"_635\\\":9775,\\\"_636\\\":9795,\\\"_638\\\":9788,\\\"_640\\\":9796},{\\\"_635\\\":9764,\\\"_636\\\":9774,\\\"_638\\\":9775,\\\"_640\\\":9776},{\\\"_635\\\":9302,\\\"_636\\\":9763,\\\"_638\\\":9764,\\\"_640\\\":9765},{\\\"_635\\\":9289,\\\"_636\\\":9301,\\\"_638\\\":9302,\\\"_640\\\":9303},{\\\"_635\\\":9280,\\\"_636\\\":9288,\\\"_638\\\":9289,\\\"_640\\\":9290},{\\\"_635\\\":9268,\\\"_636\\\":9279,\\\"_638\\\":9280,\\\"_640\\\":9281},{\\\"_635\\\":9248,\\\"_636\\\":9267,\\\"_638\\\":9268,\\\"_640\\\":9269},{\\\"_635\\\":9236,\\\"_636\\\":9247,\\\"_638\\\":9248,\\\"_640\\\":9249},{\\\"_635\\\":9227,\\\"_636\\\":9235,\\\"_638\\\":9236,\\\"_640\\\":9237},{\\\"_635\\\":9217,\\\"_636\\\":9226,\\\"_638\\\":9227,\\\"_640\\\":9228},{\\\"_635\\\":9207,\\\"_636\\\":9216,\\\"_638\\\":9217,\\\"_640\\\":9218},{\\\"_635\\\":9197,\\\"_636\\\":9206,\\\"_638\\\":9207,\\\"_640\\\":9208},{\\\"_635\\\":9186,\\\"_636\\\":9196,\\\"_638\\\":9197,\\\"_640\\\":9198},{\\\"_635\\\":9175,\\\"_636\\\":9185,\\\"_638\\\":9186,\\\"_640\\\":9187},{\\\"_635\\\":9164,\\\"_636\\\":9174,\\\"_638\\\":9175,\\\"_640\\\":9176},{\\\"_635\\\":5757,\\\"_636\\\":9163,\\\"_638\\\":9164,\\\"_640\\\":9165},{\\\"_635\\\":5742,\\\"_636\\\":5756,\\\"_638\\\":5757,\\\"_640\\\":5758},{\\\"_635\\\":5725,\\\"_636\\\":5741,\\\"_638\\\":5742,\\\"_640\\\":5743},{\\\"_635\\\":5633,\\\"_636\\\":5724,\\\"_638\\\":5725,\\\"_640\\\":5726},{\\\"_635\\\":5634,\\\"_636\\\":5709,\\\"_638\\\":5633,\\\"_640\\\":5710},{\\\"_635\\\":5622,\\\"_636\\\":5700,\\\"_638\\\":5634,\\\"_640\\\":5701},{\\\"_635\\\":5611,\\\"_636\\\":5621,\\\"_638\\\":5622,\\\"_640\\\":5623},{\\\"_635\\\":5265,\\\"_636\\\":5610,\\\"_638\\\":5611,\\\"_640\\\":5612},{\\\"_635\\\":5251,\\\"_636\\\":5264,\\\"_638\\\":5265,\\\"_640\\\":5266},{\\\"_635\\\":5238,\\\"_636\\\":5250,\\\"_638\\\":5251,\\\"_640\\\":5252},{\\\"_635\\\":5222,\\\"_636\\\":5237,\\\"_638\\\":5238,\\\"_640\\\":5239},{\\\"_635\\\":4947,\\\"_636\\\":5221,\\\"_638\\\":5222,\\\"_640\\\":5223},{\\\"_635\\\":4948,\\\"_636\\\":5196,\\\"_638\\\":4947,\\\"_640\\\":5197},{\\\"_635\\\":4949,\\\"_636\\\":5185,\\\"_638\\\":4948,\\\"_640\\\":5186},{\\\"_635\\\":5105,\\\"_636\\\":5114,\\\"_638\\\":4949,\\\"_640\\\":5115},{\\\"_635\\\":5033,\\\"_636\\\":5104,\\\"_638\\\":5105,\\\"_640\\\":5106},{\\\"_635\\\":5023,\\\"_636\\\":5032,\\\"_638\\\":5033,\\\"_640\\\":5034},{\\\"_635\\\":4927,\\\"_636\\\":5022,\\\"_638\\\":5023,\\\"_640\\\":5024},{\\\"_635\\\":4916,\\\"_636\\\":4926,\\\"_638\\\":4927,\\\"_640\\\":4928},{\\\"_635\\\":2972,\\\"_636\\\":4915,\\\"_638\\\":4916,\\\"_640\\\":4917},{\\\"_635\\\":2951,\\\"_636\\\":2971,\\\"_638\\\":2972,\\\"_640\\\":2973},{\\\"_635\\\":2935,\\\"_636\\\":2950,\\\"_638\\\":2951,\\\"_640\\\":2952},{\\\"_635\\\":2675,\\\"_636\\\":2934,\\\"_638\\\":2935,\\\"_640\\\":2936},{\\\"_635\\\":2676,\\\"_636\\\":2914,\\\"_638\\\":2675,\\\"_640\\\":2915},{\\\"_635\\\":2677,\\\"_636\\\":2901,\\\"_638\\\":2676,\\\"_640\\\":2902},{\\\"_635\\\":2835,\\\"_636\\\":2844,\\\"_638\\\":2677,\\\"_640\\\":2845},{\\\"_635\\\":2773,\\\"_636\\\":2834,\\\"_638\\\":2835,\\\"_640\\\":2836},{\\\"_635\\\":2755,\\\"_636\\\":2772,\\\"_638\\\":2773,\\\"_640\\\":2774},{\\\"_635\\\":2650,\\\"_636\\\":2754,\\\"_638\\\":2755,\\\"_640\\\":2756},{\\\"_635\\\":2630,\\\"_636\\\":2649,\\\"_638\\\":2650,\\\"_640\\\":2651},{\\\"_635\\\":639,\\\"_636\\\":2629,\\\"_638\\\":2630,\\\"_640\\\":2631},{\\\"_635\\\":81,\\\"_636\\\":637,\\\"_638\\\":639,\\\"_640\\\":641},\\\"id\\\",\\\"message\\\",{\\\"_635\\\":81,\\\"_642\\\":643,\\\"_54\\\":644,\\\"_56\\\":645,\\\"_646\\\":647,\\\"_648\\\":649,\\\"_650\\\":34,\\\"_651\\\":652,\\\"_653\\\":654,\\\"_655\\\":656,\\\"_657\\\":658},\\\"parent\\\",\\\"71ce79e3-d359-46f2-949b-fc5abc9e4280\\\",\\\"children\\\",[],\\\"author\\\",{\\\"_2624\\\":2625,\\\"_653\\\":2626},1789025538.388774,1789025563.377128,\\\"content\\\",{\\\"_2619\\\":2620,\\\"_2621\\\":2622},\\\"status\\\",\\\"finished_successfully\\\",\\\"end_turn\\\",\\\"weight\\\",1,\\\"metadata\\\",{\\\"_659\\\":660,\\\"_661\\\":34,\\\"_662\\\":663,\\\"_664\\\":665,\\\"_62\\\":666,\\\"_667\\\":668,\\\"_669\\\":670,\\\"_671\\\":672,\\\"_673\\\":674,\\\"_675\\\":34,\\\"_676\\\":677,\\\"_678\\\":679,\\\"_680\\\":681,\\\"_682\\\":681,\\\"_683\\\":672,\\\"_66\\\":67,\\\"_684\\\":34,\\\"_685\\\":639,\\\"_686\\\":687,\\\"_688\\\":10},\\\"recipient\\\",\\\"all\\\",\\\"channel\\\",\\\"final\\\",\\\"finish_details\\\",{\\\"_50\\\":2615,\\\"_2616\\\":2617},\\\"is_complete\\\",\\\"content_references\\\",[2268,2269,2270,2271,2272,2273,2274,2275,2276,2277,2278,2279,2280,2281,2282,2283,2284,2285,2286,2287,2288,2289,2290,2291],\\\"search_result_groups\\\",[723,724,725,726,727,728,729,730,731,732,733,734,735],[689,690,691,692,693,694,695,696,697,698,699,700,701,702,703,704,705,706,707,708,709,710,711,712,713,714,715,716,717,718,719,720,721,722],\\\"story_events\\\",[],\\\"citations\\\",[],\\\"resolved_model_slug\\\",\\\"gpt-5-6-t-mini\\\",\\\"cot_version\\\",\\\"v5\\\",\\\"conversation_followup_suggestions_eligible\\\",\\\"request_id\\\",\\\"b7d295c3-82f3-482f-8c5a-c39c4f67959c\\\",\\\"message_type\\\",\\\"next\\\",\\\"turn_exchange_id\\\",\\\"ca93db11-7779-47ed-8e3d-d459a88a6b31\\\",\\\"working_turn_id\\\",\\\"model_slug\\\",\\\"can_save\\\",\\\"parent_id\\\",\\\"turn_id\\\",\\\"2cc45c9c-a09f-4619-846b-fe7c7a0586fd\\\",\\\"shared_conversation_id\\\",\\\"https://educationmalaysia.gov.my/get-in-touch/faq\\\",\\\"https://educationmalaysia.gov.my/get-in-touch/faq?utm_source=chatgpt.com\\\",\\\"https://erasmus-plus.ec.europa.eu/opportunities/individuals/students/studying-abroad\\\",\\\"https://erasmus-plus.ec.europa.eu/opportunities/individuals/students/studying-abroad?utm_source=chatgpt.com\\\",\\\"https://esd.imi.gov.my/portal/latest-news/announcement/announcement-266-ep-salary-policy-2026/\\\",\\\"https://esd.imi.gov.my/portal/latest-news/announcement/announcement-266-ep-salary-policy-2026/?utm_source=chatgpt.com\\\",\\\"https://university.taylors.edu.my/en/study/explore-all-programmes/computer-science/undergraduate/bachelor-of-computer-science.html\\\",\\\"https://university.taylors.edu.my/en/study/explore-all-programmes/computer-science/undergraduate/bachelor-of-computer-science.html?utm_source=chatgpt.com\\\",\\\"https://www.apu.edu.my/course/bsc-hons-in-computer-science\\\",\\\"https://www.apu.edu.my/course/bsc-hons-in-computer-science?utm_source=chatgpt.com\\\",\\\"https://www.gov.uk/graduate-visa/course-you-studied\\\",\\\"https://www.gov.uk/graduate-visa/course-you-studied?utm_source=chatgpt.com\\\",\\\"https://www.gov.uk/student-visa\\\",\\\"https://www.gov.uk/student-visa?utm_source=chatgpt.com\\\",\\\"https://www.mom.gov.sg/passes-and-permits/employment-pass\\\",\\\"https://www.mom.gov.sg/passes-and-permits/employment-pass/eligibility?locale=en\\\",\\\"https://www.mom.gov.sg/passes-and-permits/employment-pass/eligibility?locale=en\\u0026utm_source=chatgpt.com\\\",\\\"https://www.mom.gov.sg/passes-and-permits/employment-pass?utm_source=chatgpt.com\\\",\\\"https://www.mom.gov.sg/passes-and-permits/s-pass/eligibility\\\",\\\"https://www.mom.gov.sg/passes-and-permits/s-pass/eligibility?utm_source=chatgpt.com\\\",\\\"https://www.mom.gov.sg/passes-and-permits/s-pass/key-facts\\\",\\\"https://www.mom.gov.sg/passes-and-permits/s-pass/key-facts?utm_source=chatgpt.com\\\",\\\"https://www.reddit.com/r/malaysiauni/comments/1lefl48/hunting_job_after_graduation_for_international/\\\",\\\"https://www.reddit.com/r/malaysiauni/comments/1lefl48/hunting_job_after_graduation_for_international/?utm_source=chatgpt.com\\\",\\\"https://www.reddit.com/r/malaysiauni/comments/1n5st2o/why_do_international_students_choose_malaysia_for/\\\",\\\"https://www.reddit.com/r/malaysiauni/comments/1n5st2o/why_do_international_students_choose_malaysia_for/?utm_source=chatgpt.com\\\",\\\"https://www.reddit.com/r/malaysiauni/comments/1p16ro7/why_do_international_students_choose_malaysia_for/\\\",\\\"https://www.reddit.com/r/malaysiauni/comments/1p16ro7/why_do_international_students_choose_malaysia_for/?utm_source=chatgpt.com\\\",\\\"https://www.reddit.com/r/malaysiauni/comments/1rsgyx9/full_time_jobs_for_fresh_graduates/\\\",\\\"https://www.reddit.com/r/malaysiauni/comments/1rsgyx9/full_time_jobs_for_fresh_graduates/?utm_source=chatgpt.com\\\",\\\"https://www.reddit.com/r/malaysiauni/comments/1tltky3/parttime_jobs_for_international_students/\\\",\\\"https://www.reddit.com/r/malaysiauni/comments/1tltky3/parttime_jobs_for_international_students/?utm_source=chatgpt.com\\\",\\\"https://www.reddit.com/r/malaysiauni/comments/1vw5bhp/international_students_what_are_your_plans_after/\\\",\\\"https://www.reddit.com/r/malaysiauni/comments/1vw5bhp/international_students_what_are_your_plans_after/?utm_source=chatgpt.com\\\",{\\\"_50\\\":736,\\\"_737\\\":2163,\\\"_739\\\":2164},{\\\"_50\\\":736,\\\"_737\\\":2111,\\\"_739\\\":2112},{\\\"_50\\\":736,\\\"_737\\\":1761,\\\"_739\\\":1762},{\\\"_50\\\":736,\\\"_737\\\":1675,\\\"_739\\\":1676},{\\\"_50\\\":736,\\\"_737\\\":1533,\\\"_739\\\":1534},{\\\"_50\\\":736,\\\"_737\\\":1467,\\\"_739\\\":1468},{\\\"_50\\\":736,\\\"_737\\\":1401,\\\"_739\\\":1402},{\\\"_50\\\":736,\\\"_737\\\":1190,\\\"_739\\\":1191},{\\\"_50\\\":736,\\\"_737\\\":1060,\\\"_739\\\":1061},{\\\"_50\\\":736,\\\"_737\\\":992,\\\"_739\\\":993},{\\\"_50\\\":736,\\\"_737\\\":906,\\\"_739\\\":907},{\\\"_50\\\":736,\\\"_737\\\":850,\\\"_739\\\":851},{\\\"_50\\\":736,\\\"_737\\\":738,\\\"_739\\\":740},\\\"search_result_group\\\",\\\"domain\\\",\\\"ucsiuniversity.edu.my\\\",\\\"entries\\\",[741,742,743,744,745,746,747,748,749,750,751,752,753,754,755,756,757,758],{\\\"_50\\\":759,\\\"_41\\\":847,\\\"_53\\\":790,\\\"_762\\\":763,\\\"_764\\\":848,\\\"_766\\\":792,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":843,\\\"_53\\\":790,\\\"_762\\\":844,\\\"_764\\\":845,\\\"_766\\\":792,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":837,\\\"_53\\\":838,\\\"_762\\\":839,\\\"_764\\\":840,\\\"_766\\\":841,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":833,\\\"_53\\\":790,\\\"_762\\\":834,\\\"_764\\\":835,\\\"_766\\\":-5,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":830,\\\"_53\\\":815,\\\"_762\\\":763,\\\"_764\\\":831,\\\"_766\\\":817,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":826,\\\"_53\\\":805,\\\"_762\\\":827,\\\"_764\\\":828,\\\"_766\\\":-5,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":822,\\\"_53\\\":823,\\\"_762\\\":786,\\\"_764\\\":824,\\\"_766\\\":-5,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":819,\\\"_53\\\":810,\\\"_762\\\":786,\\\"_764\\\":820,\\\"_766\\\":812,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":814,\\\"_53\\\":815,\\\"_762\\\":786,\\\"_764\\\":816,\\\"_766\\\":817,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":809,\\\"_53\\\":810,\\\"_762\\\":786,\\\"_764\\\":811,\\\"_766\\\":812,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":804,\\\"_53\\\":805,\\\"_762\\\":806,\\\"_764\\\":807,\\\"_766\\\":-5,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":799,\\\"_53\\\":800,\\\"_762\\\":801,\\\"_764\\\":802,\\\"_766\\\":-5,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":794,\\\"_53\\\":795,\\\"_762\\\":796,\\\"_764\\\":797,\\\"_766\\\":-5,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":789,\\\"_53\\\":790,\\\"_762\\\":763,\\\"_764\\\":791,\\\"_766\\\":792,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":785,\\\"_53\\\":761,\\\"_762\\\":786,\\\"_764\\\":787,\\\"_766\\\":-5,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":779,\\\"_53\\\":780,\\\"_762\\\":781,\\\"_764\\\":782,\\\"_766\\\":783,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":774,\\\"_53\\\":775,\\\"_762\\\":776,\\\"_764\\\":777,\\\"_766\\\":-5,\\\"_767\\\":738},{\\\"_50\\\":759,\\\"_41\\\":760,\\\"_53\\\":761,\\\"_762\\\":763,\\\"_764\\\":765,\\\"_766\\\":-5,\\\"_767\\\":738},\\\"search_result\\\",\\\"https://www.ucsiuniversity.edu.my/international-degree-programme?utm_source=chatgpt.com\\\",\\\"International Degree Pathway Programme\\\",\\\"snippet\\\",\\\"Contact Us  Address  Global Engagement Office (GEO) Block G, Level 10, UCSI University, 1 Jalan UCSI, UCSI Heights (Taman Connaught), Cheras 56000, Kuala Lumpur, Malaysia.  Tel  +603 9101 8880 ext. 20...\\\",\\\"ref_id\\\",{\\\"_768\\\":769,\\\"_770\\\":771,\\\"_772\\\":773},\\\"pub_date\\\",\\\"attribution\\\",\\\"turn_index\\\",2,\\\"ref_type\\\",\\\"search\\\",\\\"ref_index\\\",131,\\\"https://www.ucsiuniversity.edu.my/International-Degree-Pathways/application-and-procedure?utm_source=chatgpt.com\\\",\\\"Application and Procedure\\\",\\\"Global Engagement Office  Sub Menu  * About Us * International Degree Pathways (IDP) * Transnational Education Partners (TNE) * Student Exchange Programme * Overview * Inbound Student Exchange Progra...\\\",{\\\"_768\\\":769,\\\"_770\\\":771,\\\"_772\\\":778},129,\\\"https://www.ucsiuniversity.edu.my/international-students/student-visas?utm_source=chatgpt.com\\\",\\\"Student Visa\\\",\\\"International Students  Sub Menu  * Overview * Admission Procedure * Pre-arrival * Arrival * Student Visa * Insurance * Student Experience  iframe  STUDENT PASS POLICIES FOR INTERNATIONAL STUDENTS  I...\\\",{\\\"_768\\\":769,\\\"_770\\\":771,\\\"_772\\\":784},1758697420,128,\\\"https://www.bangladesh.ucsiuniversity.edu.my/International-Degree-Pathways/idp-programmes?utm_source=chatgpt.com\\\",\\\"Image: IUCC  Global Engagement Office  Sub Menu  * About Us * International Degree Pathways (IDP) * Transnational Education Partners (TNE) * Student Exchange Programme * Overview * Inbound Student Ex...\\\",{\\\"_768\\\":769,\\\"_770\\\":771,\\\"_772\\\":788},127,\\\"https://www.ucsiuniversity.edu.my/node/5609?utm_source=chatgpt.com\\\",\\\"Student Exchange Programme\\\",{\\\"_768\\\":769,\\\"_770\\\":771,\\\"_772\\\":793},1531448826,123,\\\"https://ch.ucsiuniversity.edu.my/application-guidelines?utm_source=chatgpt.com\\\",\\\"Application Guidelines\\\",\\\"STUDENT MOBILITY PROGRAMME  Sub Menu  * Overview * About the Programme * Courses Offered * Industrial Training * Application Guidelines * International Networking \\u0026 Multicultural Exposure * Life at U...\\\",{\\\"_768\\\":769,\\\"_770\\\":771,\\\"_772\\\":798},121,\\\"https://www.ucsiuniversity.edu.my/achievements/faculty-of-applied-science/all/lecturer?utm_source=chatgpt.com\\\",\\\"Lecturer Achievements | Faculty of Applied Sciences\\\",\\\"Image: Faculty of Applied Science  Faculty of Applied Sciences  Sub Menu  * About Us * Programmes * Staff * Research \\u0026 Publications * Researchers * Publications * Books * Facilities * Student Achieve...\\\",{\\\"_768\\\":652,\\\"_770\\\":771,\\\"_772\\\":803},98,\\\"https://www.ucsiuniversity.edu.my/admission-procedure/international/kuching?display=Kuching-Campus\\u0026utm_source=chatgpt.com\\\",\\\"Admission Procedure | International Students\\\",\\\"International Students  Sub Menu  * Overview * Admission Procedure * Pre-arrival * Arrival * Student Visa * Insurance * Student Experience  iframe  * Kuala Lumpur / Springhill (Lukut) Campus * Kuchin...\\\",{\\\"_768\\\":652,\\\"_770\\\":771,\\\"_772\\\":808},95,\\\"https://www.ucsiuniversity.edu.my/inbound-student-exchange-programme?utm_source=chatgpt.com\\\",\\\"Inbound Student Exchange Programme\\\",{\\\"_768\\\":652,\\\"_770\\\":771,\\\"_772\\\":813},1560227606,92,\\\"https://www.bangladesh.ucsiuniversity.edu.my/node/8630?utm_source=chatgpt.com\\\",\\\"Outbound Student Exchange Programme\\\",{\\\"_768\\\":652,\\\"_770\\\":771,\\\"_772\\\":818},1560239028,90,\\\"https://www.bangladesh.ucsiuniversity.edu.my/node/8625?utm_source=chatgpt.com\\\",{\\\"_768\\\":652,\\\"_770\\\":771,\\\"_772\\\":821},89,\\\"https://www.ucsiuniversity.edu.my/about-us/global-engagement-office?utm_source=chatgpt.com\\\",\\\"About Us | Global Engagement Office\\\",{\\\"_768\\\":652,\\\"_770\\\":771,\\\"_772\\\":825},88,\\\"https://www.ucsiuniversity.edu.my/admission-procedure/international/Kuala-lumpur?display=Kuala-Lumpur-%2F-Springhill-%28Seremban%2FPD%29-Campus\\u0026utm_source=chatgpt.com\\\",\\\"Step 1  Register Online  The Online Registration Form is to be completed and acknowledged by applicants. To register, click here. Prior to registering, you are advised to check on your eligibility st...\\\",{\\\"_768\\\":652,\\\"_770\\\":771,\\\"_772\\\":829},86,\\\"https://www.ucsiuniversity.edu.my/node/8630?utm_source=chatgpt.com\\\",{\\\"_768\\\":652,\\\"_770\\\":771,\\\"_772\\\":832},81,\\\"https://ch.ucsiuniversity.edu.my/student-exchange-programme?utm_source=chatgpt.com\\\",\\\"\n Malaysia\\\\n\\\\nYou do a 3-year computing degree.\\\\n\\\\nDuring those three years:\\\\n\\\\n**CGPA high + English + programming + GitHub + internships + CRM projects + professional networking**\\\\n\\\\nThen:\\\\n\\\\n### Stage 2\\\\nMalaysia \n Pakistan\\\\n\\\\nYou have:\\\\n\\\\n**51% Intermediate**\\\\n\\\\n**2024 completion**\\\\n\\\\n**limited money**\\\\n\\\\n**growing CRM/software experience**\\\\n\\\\nYou need to improve academically and professionally.\\\\n\\\\n\n backend\\\\n\\\\nBy Year 3:\\\\n\\\\nCRM architecture \n\\\\n\\\\n---\\\\n\\\\n# 18. My current judgement of Malaysia for YOU\\\\n\\\\n### As a permanent destination:\\\\n\\\\n**5/10**\\\\n\\\\nI don't love it for you.\\\\n\\\\n### As a cheap English-language education platform:\\\\n\\\\n**7/10**\\\\n\\\\nPotentially useful.\\\\n\\\\n### As a path to Singapore:\\\\n\\\\n**5/10**\\\\n\\\\nPossible, but highly competitive.\\\\n\\\\n### As a path to a European master's:\\\\n\\\\n**8/10 IF we choose the university carefully**\\\\n\\\\nThis is where I become much more positive.\\\\n\\\\n### As a path relying heavily on part-time jobs:\\\\n\\\\n**3/10**\\\\n\\\\nI would not approve this plan for my son.\\\\n\\\\n### As a path for your long-term IT/CRM career:\\\\n\\\\n**7/10**, provided you use Malaysia to build your profile rather than waiting for Malaysia to give you a job.\\\\n\\\\n---\\\\n\\\\n# The biggest discovery from this research\\\\n\\\\nI actually think your question has uncovered a **potentially better strategy than our original country ranking**.\\\\n\\\\nInstead of asking:\\\\n\\\\n\\u003e **Italy or Romania or Malaysia?**\\\\n\\\\nwe should ask:\\\\n\\\\n## \n Build yourself\\\\n\\\\nDuring the degree:\\\\n\\\\n**Italian/German/another European language + internships + GitHub + CRM/software portfolio + local work experience + networking + European CV**\\\\n\\\\nYour biggest objective isn't earning \n Finland  \\\\netc.\\\\n\\\\nYou would be applying as:\\\\n\\\\n\\u003e **European-educated software/CRM professional with local experience**\\\\n\\\\nrather than:\\\\n\\\\n\\u003e **Pakistani student with 51% Intermediate looking for sponsorship from abroad.**\\\\n\\\\nThat is an enormous difference.\\\\n\\\\n---\\\\n\\\\n# \n\\\\n\\\\nThat's unusually attractive.\\\\n\\\\nAnd for someone pursuing:\\\\n\\\\n**software + automation + SaaS + CRM + digital business**\\\\n\\\\nthe country itself is conceptually a very good fit.\\\\n\\\\nBut here's the catch:\\\\n\\\\n**Estonia is not automatically a cheap country.**\\\\n\\\\nYour 18 lakh budget makes the financial side much more important than the technology ecosystem.\\\\n\\\\nSo I would investigate Estonia **only if we find a genuinely affordable programme and realistic financing**.\\\\n\\\\n---\\\\n\\\\n# \n\\\\n\\\\nFor your career:\\\\n\\\\n**CRM + software + automation + backend + business systems**\\\\n\\\\nGermany makes much more sense as a long-term target than Malaysia.\\\\n\\\\nBut you currently don't have the financial strength to treat Germany casually.\\\\n\\\\nSo I'd rather get you **into Europe safely first** than force Germany prematurely.\\\\n\\\\n---\\\\n\\\\n# \n pathway that some European countries provide.\\\\n\\\\nMalaysia isn't bad.\\\\n\\\\n**It is simply less aligned with your objective.**\\\\n\\\\n---\\\\n\\\\n# One HUGE misconception I want you to avoid\\\\n\\\\nSuppose you are studying in Romania.\\\\n\\\\nYou get a beautiful job advertisement:\\\\n\\\\n\\u003e **PHP/CRM Developer \n CRM/software internship \n\\\\n\\\\nThat fits your existing direction in **PHP, CRM, business software and automation** better linguistically than Romania might.\\\\n\\\\nBut there is a second problem:\\\\n\\\\n### Staying in Malaysia after graduation\\\\n\\\\nMalaysia does have a **Graduate Pass**, but the current government eligibility list is nationality-specific, and **Pakistan is not on the current eligible-country list** shown by Education Malaysia. \n\\\\n\\\\nSo my rule for you would be:\\\\n\\\\n\\u003e **Italy only works as a career strategy if you learn Italian seriously and build a strong technical career while studying.**\\\\n\\\\nFor your CRM/software ambitions, that means you should not arrive in Italy intending to remain an ordinary part-time worker. You should be building toward **software developer / CRM / business systems / automation roles**.\\\\n\\\\n---\\\\n\\\\n# Italy has one Pakistan-specific problem right now\\\\n\\\\nThis is important because you are from Faisalabad.\\\\n\\\\nAs of September 2026, the Italian Embassy in Pakistan has **permanently closed the Faisalabad and Multan visa application centres**. Applications are now handled"
            }
          }
        }
      ]
    }
  ]
}