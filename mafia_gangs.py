from pytg.receiver import Receiver  # get messages
from pytg.sender import Sender  # send messages, and other querys.
from pytg.utils import coroutine

from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from asyncio import Lock
from collections import deque
import re

def main():
	# get a Receiver instance, to get messages.
	receiver = Receiver(host="localhost", port=4458)

	# get a Sender instance, to send messages, and other querys.
	sender = Sender(host="localhost", port=4458)

	# start the Receiver, so we can get messages!
	receiver.start()  # note that the Sender has no need for a start function.

	order_poll = []
	fight_poll = deque([] for _ in range(0, 60))

	fight_codes = ["/f_IB941641", "/f_IA42478", "/f_I3269", "/f_I405985", "/f_I3C237", "/f_I8741134", "/f_I3C8593"]
	for code in fight_codes:
		fight_order(code, fight_poll)

	scheduler = BackgroundScheduler()
	scheduler.add_job(fight, 'interval', seconds=60, args=[sender, order_poll, fight_poll])

	collect(order_poll)
	scheduler.add_job(collect, 'interval', minutes=61, args=[order_poll])

	scheduler.add_job(send_order, 'interval', seconds=1, args=[sender, order_poll])

	scheduler.start()

	# add "example_function" function as message listener. You can supply arguments here (like sender).
	receiver.message(message_loop(sender, order_poll, fight_poll))  # now it will call the example_function and yield the new messages.

	# continues here, after exiting the while loop in example_function()

	# please, no more messages. (we could stop the the cli too, with sender.safe_quit() )
	receiver.stop()
	scheduler.shutdown()

	# continues here, after exiting while loop in example_function()
	print("I am done!")

	# the sender will disconnect after each send, so there is no need to stop it.
	# if you want to shutdown the telegram cli:
	# sender.safe_quit() # this shuts down the telegram cli.
	# sender.quit() # this shuts down the telegram cli, without waiting for downloads to complete.
# end def main

def fight(sender, order_poll, fight_poll):
	now = datetime.now().minute
	if now == 0:
		fight_poll.rotate(1)
		return # Don't attack on minute 0 to prevent repeated attacks

	for code in fight_poll[now]:
		order_poll.append(code)

def collect(order_poll):
	place_order("/collect", order_poll)

lock = Lock()
@coroutine
def message_loop(sender, order_poll, fight_poll):  # name "message_loop" and given parameters are defined in main()
	try:
		while True:  # loop for a session.
			msg = (yield)
			if should_skip_message(msg):
				continue

			print(lock.locked() and "Received order's reply" or "Received message. Processing...")
			while not should_skip_message(msg) and not received_success(sender, msg.text, order_poll, fight_poll):
				print("Failed to process. Trying again...")
				msg = (yield)

			if lock.locked():
				lock.release()
				print("Send order unlocked\n")

			# done.
	except GeneratorExit:
		# the generator (pytg) exited (got a KeyboardIterrupt).
		pass
	except KeyboardInterrupt:
		# we got a KeyboardIterrupt(Ctrl+C)
		pass
	else:
		# the loop exited without exception, becaues _quit was set True
		pass

def send_order(sender, order_poll):
	for i in send_order_aux(sender, order_poll):
		continue

def send_order_aux(sender, order_poll):
	if len(order_poll) == 0:
		return

	print("Send order is", lock.locked() and "locked" or "unlocked")
	if not lock.locked():
		if order_poll[0] == "do nothing":
			print("Ignoring received message")
		elif order_poll[0] is not None:
			print("Sending order: " + order_poll[0])
			sender.msg("@mafiagangsbot", order_poll[0])
		print("Locking send order...\n")
		yield from lock


def place_order(order, order_poll):
	print("Placing order (" + order + ") on the queue")

	if any([order in p for p in ["/cure", "/levelup", "Energy (+1)", "do nothing"]]):
		print("Priority order received, moving to the front of the queue")
		order_poll.insert(0, order)
	else:
		order_poll.append(order)

	print()

def fight_order(code, fight_poll):
	# Insert code into the next iteration of fight()
	now = (datetime.now().minute + 1) % 60
	for codes in fight_poll:
		if code in codes:
			return

	print("Inserting fight code (" + code + ") on fight list\n")
	fight_poll[now].append(code)

def spend_order(msg, order_poll):
	estates = [
		["/buy_wmb", 50, 0],
		["/buy_wrw", 25, 0],
		["/buy_wps", 15, 0],
		["/buy_wwp", 10, 0],
		["/buy_wtr", 5, 0],
	]

	profit = int(re.findall(r"(\d+)", msg)[0])
	for building in estates:
		while building[1] <= profit:
			building[2] = building[2] + 1
			profit = profit - building[1]

		if building[2] > 0:
			place_order(building[0] + "_" + str(building[2]), order_poll)

def received_success(sender, msg, order_poll, fight_poll):
	if "much requests" in msg:
		return False

	if "Revenge attack" in msg:
		code = re.match(".+(/.+)", msg.splitlines()[1]).group(1)
		print("You were attacked by " + code)

		fight_order(code, fight_poll)
		place_order("/cure", order_poll)
		# This message does not mean our order was completed
		# So we return to prevent it from being removed from order_poll
		return True

	last_order = None
	if len(order_poll) > 0:
		last_order = order_poll.pop(0)
		print("Removing sent order: " + last_order)

	if any([p in msg for p in ["hospital", "suffered"]]):
		if "hospital" in msg and last_order is not None and last_order != "/cure":
			print("Attack failed, insuficient health. Trying again.")
			order_poll.insert(0, last_order)
		place_order("/cure", order_poll)

	if last_order is not None and "That gang is fighting" in msg:
		print("Attack failed. Gang is in fight, try again.")
		place_order(last_order, order_poll)

	if "/levelup" in msg and "/levelup" not in order_poll:
		print("You leveled up. Clearing queue from cure orders.")
		while "/cure" in order_poll:
			order_poll.remove("/cure")
		order_poll.insert(0, "/mission_29")
		place_order("Energy (+1)", order_poll)
		place_order("/levelup", order_poll)
		place_order("do nothing", order_poll)

	if "choice" in msg:
		place_order("Energy (+1)", order_poll)

	if "Energy restored" in msg and "/mission_29" not in order_poll:
		place_order("/mission_29", order_poll)

	if "collected" in msg:
		spend_order(msg, order_poll)

	return True


def should_skip_message(msg):
	"""
	Checks if the event is a message, is not from the bot itself, is in a user-to-user (user-to-bot) chat and has text.
	Also sets the online status to online.
	:keyword only_allow_user: (Optional) Ignore all messages which are not from this user (checks msg.sender.cmd)
	Basically the same code as in bot_ping.py, a little bit extended.
	"""

	if msg.event != "message":
		return True  # is not a message.
	if "username" not in msg.sender or msg.sender.username != "mafiagangsbot":
		return True
	if msg.own:  # the bot has send this message.
		return True  # we don't want to process this message.
	if msg.receiver.type != "user":
		return True
	if "text" not in msg or msg.text is None:  # we have media instead.
		return True  # and again, because we want to process only text message.
		# Everything in pytg will be unicode. If you use python 3 thats no problem,
		# just if you use python 2 you have to be carefull! (better switch to 3)
		# for convinience of py2 users there is a to_unicode(<string>) in pytg.encoding
		# for python 3 the using of it is not needed.
		# But again, use python 3, as you have a chat with umlaute and emojis.
		# This WILL brake your python 2 code at some point!
	if any([p in msg.text for p in ["You have sent", "Stamina is restored", "your gang code"]]):
		return True
	return False

# # program starts here # #
if __name__ == '__main__':
	main()  # executing main function.
# Last command of file (so everything needed is already loaded above)
